"""MinIO/S3 model storage for syncing ML models between environments."""

import logging
import os
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class ModelStore:
    """S3-compatible model storage (MinIO) for upload, download, archive, rollback, cleanup."""

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        use_ssl: bool = False,
    ):
        self._bucket = bucket
        protocol = "https" if use_ssl else "http"
        self._s3 = boto3.client(
            "s3",
            endpoint_url=f"{protocol}://{endpoint}",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="us-east-1",
        )
        self._ensure_bucket()

    def _ensure_bucket(self):
        try:
            self._s3.head_bucket(Bucket=self._bucket)
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchBucket"):
                self._s3.create_bucket(Bucket=self._bucket)
                logger.info("Created bucket %s", self._bucket)
            else:
                raise

    def upload_model(self, pair_slug: str, local_dir: str) -> str:
        """Upload model files from local_dir to pair_slug/latest/, archiving existing."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self._archive_latest(pair_slug, timestamp)

        prefix = f"{pair_slug}/latest/"
        for filename in os.listdir(local_dir):
            filepath = os.path.join(local_dir, filename)
            if os.path.isfile(filepath):
                key = f"{prefix}{filename}"
                self._s3.upload_file(
                    Filename=filepath, Bucket=self._bucket, Key=key
                )
                logger.info("Uploaded %s", key)

        return timestamp

    def download_model(self, pair_slug: str, local_dir: str) -> bool:
        """Download latest model files for pair_slug to local_dir. Returns False if no latest."""
        prefix = f"{pair_slug}/latest/"
        resp = self._s3.list_objects_v2(Bucket=self._bucket, Prefix=prefix)
        if resp.get("KeyCount", 0) == 0:
            return False

        os.makedirs(local_dir, exist_ok=True)
        for obj in resp["Contents"]:
            key = obj["Key"]
            filename = key.split("/")[-1]
            dest = os.path.join(local_dir, filename)
            self._s3.download_file(
                Bucket=self._bucket, Key=key, Filename=dest
            )
            logger.info("Downloaded %s → %s", key, dest)

        return True

    def list_versions(self, pair_slug: str) -> list[str]:
        """List archived version timestamps for a pair, sorted ascending."""
        prefix = f"{pair_slug}/archive/"
        resp = self._s3.list_objects_v2(
            Bucket=self._bucket, Prefix=prefix, Delimiter="/"
        )
        versions = []
        for cp in resp.get("CommonPrefixes", []):
            # "btc_usdt_swap/archive/20260409_193008/" → "20260409_193008"
            version = cp["Prefix"].rstrip("/").split("/")[-1]
            versions.append(version)
        return sorted(versions)

    def rollback(self, pair_slug: str, version: str):
        """Replace latest with a specific archived version."""
        archive_prefix = f"{pair_slug}/archive/{version}/"
        resp = self._s3.list_objects_v2(Bucket=self._bucket, Prefix=archive_prefix)
        if resp.get("KeyCount", 0) == 0:
            raise ValueError(f"Archive version {version} not found for {pair_slug}")

        archive_files = resp["Contents"]
        latest_prefix = f"{pair_slug}/latest/"
        latest_resp = self._s3.list_objects_v2(Bucket=self._bucket, Prefix=latest_prefix)
        for obj in latest_resp.get("Contents", []):
            self._s3.delete_object(Bucket=self._bucket, Key=obj["Key"])

        for obj in archive_files:
            src_key = obj["Key"]
            filename = src_key.split("/")[-1]
            dest_key = f"{latest_prefix}{filename}"
            self._s3.copy_object(
                Bucket=self._bucket,
                CopySource={"Bucket": self._bucket, "Key": src_key},
                Key=dest_key,
            )
            logger.info("Rollback: %s → %s", src_key, dest_key)

    def cleanup_archives(self, retention_count: int = 5, retention_days: int = 30):
        """Prune old archived versions. Keep last N per pair OR newer than retention_days.

        Note: Does not paginate S3 listings; assumes <1000 pairs/versions.
        """
        # List all top-level pair prefixes
        resp = self._s3.list_objects_v2(
            Bucket=self._bucket, Delimiter="/"
        )
        pair_prefixes = [
            cp["Prefix"].rstrip("/")
            for cp in resp.get("CommonPrefixes", [])
        ]

        now = datetime.now(timezone.utc)
        for pair_slug in pair_prefixes:
            versions = self.list_versions(pair_slug)
            if len(versions) <= retention_count:
                continue

            # Oldest first — candidates for deletion are beyond retention_count
            to_keep = set(versions[-retention_count:])
            for version in versions:
                if version in to_keep:
                    continue
                # Check age
                try:
                    version_dt = datetime.strptime(version, "%Y%m%d_%H%M%S").replace(
                        tzinfo=timezone.utc
                    )
                    age_days = (now - version_dt).total_seconds() / 86400
                    if age_days < retention_days:
                        continue  # Newer than retention_days — keep
                except ValueError:
                    continue  # Can't parse timestamp — skip

                # Delete this version
                self._delete_prefix(f"{pair_slug}/archive/{version}/")
                logger.info("Cleaned up archive %s/%s", pair_slug, version)

    def _archive_latest(self, pair_slug: str, timestamp: str):
        """Copy current latest/ to archive/{timestamp}/."""
        latest_prefix = f"{pair_slug}/latest/"
        resp = self._s3.list_objects_v2(Bucket=self._bucket, Prefix=latest_prefix)
        if resp.get("KeyCount", 0) == 0:
            return

        for obj in resp["Contents"]:
            src_key = obj["Key"]
            filename = src_key.split("/")[-1]
            dest_key = f"{pair_slug}/archive/{timestamp}/{filename}"
            self._s3.copy_object(
                Bucket=self._bucket,
                CopySource={"Bucket": self._bucket, "Key": src_key},
                Key=dest_key,
            )

    def _delete_prefix(self, prefix: str):
        """Delete all objects under a prefix."""
        resp = self._s3.list_objects_v2(Bucket=self._bucket, Prefix=prefix)
        for obj in resp.get("Contents", []):
            self._s3.delete_object(Bucket=self._bucket, Key=obj["Key"])
