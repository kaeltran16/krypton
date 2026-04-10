"""Tests for MinIO model store S3 operations."""

import os
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from app.ml.model_store import ModelStore


@pytest.fixture
def mock_s3():
    """A MagicMock standing in for the boto3 S3 client."""
    return MagicMock()


@pytest.fixture
def store(mock_s3):
    """Create a ModelStore with boto3 fully mocked (no real network calls)."""
    with patch("boto3.client", return_value=mock_s3):
        mock_s3.head_bucket.return_value = {}
        return ModelStore(
            endpoint="localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            bucket="krypton-models",
            use_ssl=False,
        )


class TestModelStoreInit:
    def test_creates_bucket_if_missing(self):
        with patch("boto3.client") as mock_boto:
            client = MagicMock()
            mock_boto.return_value = client
            client.head_bucket.side_effect = ClientError(
                {"Error": {"Code": "404", "Message": "Not Found"}}, "HeadBucket"
            )

            ModelStore(
                endpoint="localhost:9000",
                access_key="key",
                secret_key="secret",
                bucket="test-bucket",
                use_ssl=False,
            )

            client.create_bucket.assert_called_once_with(Bucket="test-bucket")

    def test_skips_create_if_bucket_exists(self):
        with patch("boto3.client") as mock_boto:
            client = MagicMock()
            mock_boto.return_value = client
            client.head_bucket.return_value = {}

            ModelStore(
                endpoint="localhost:9000",
                access_key="key",
                secret_key="secret",
                bucket="test-bucket",
                use_ssl=False,
            )

            client.create_bucket.assert_not_called()


class TestUploadModel:
    def test_upload_model_uploads_all_files(self, store, mock_s3, tmp_path):
        pair_dir = tmp_path / "btc_usdt_swap"
        pair_dir.mkdir()
        (pair_dir / "ensemble_0.pt").write_bytes(b"model0")
        (pair_dir / "ensemble_1.pt").write_bytes(b"model1")
        (pair_dir / "ensemble_config.json").write_text('{"n_members": 2}')

        # No existing latest to archive
        mock_s3.list_objects_v2.return_value = {"KeyCount": 0}

        store.upload_model("btc_usdt_swap", str(pair_dir))

        upload_calls = mock_s3.upload_file.call_args_list
        uploaded_keys = {c.kwargs["Key"] for c in upload_calls}
        assert "btc_usdt_swap/latest/ensemble_0.pt" in uploaded_keys
        assert "btc_usdt_swap/latest/ensemble_1.pt" in uploaded_keys
        assert "btc_usdt_swap/latest/ensemble_config.json" in uploaded_keys

    def test_upload_model_archives_existing(self, store, mock_s3, tmp_path):
        pair_dir = tmp_path / "btc_usdt_swap"
        pair_dir.mkdir()
        (pair_dir / "ensemble_0.pt").write_bytes(b"model0")

        # Simulate existing latest
        mock_s3.list_objects_v2.return_value = {
            "KeyCount": 1,
            "Contents": [{"Key": "btc_usdt_swap/latest/ensemble_0.pt"}],
        }

        store.upload_model("btc_usdt_swap", str(pair_dir))

        # Should have copied existing to archive
        copy_calls = mock_s3.copy_object.call_args_list
        assert len(copy_calls) >= 1
        dest_key = copy_calls[0].kwargs["Key"]
        assert dest_key.startswith("btc_usdt_swap/archive/")


class TestDownloadModel:
    def test_download_model_fetches_latest(self, store, mock_s3, tmp_path):
        mock_s3.list_objects_v2.return_value = {
            "KeyCount": 2,
            "Contents": [
                {"Key": "btc_usdt_swap/latest/ensemble_0.pt"},
                {"Key": "btc_usdt_swap/latest/ensemble_config.json"},
            ],
        }

        dest = str(tmp_path / "btc_usdt_swap")
        store.download_model("btc_usdt_swap", dest)

        download_calls = mock_s3.download_file.call_args_list
        assert len(download_calls) == 2
        assert os.path.isdir(dest)

    def test_download_returns_false_if_no_latest(self, store, mock_s3, tmp_path):
        mock_s3.list_objects_v2.return_value = {"KeyCount": 0}

        dest = str(tmp_path / "btc_usdt_swap")
        result = store.download_model("btc_usdt_swap", dest)

        assert result is False


class TestListVersions:
    def test_list_versions_returns_timestamps(self, store, mock_s3):
        mock_s3.list_objects_v2.return_value = {
            "KeyCount": 3,
            "CommonPrefixes": [
                {"Prefix": "btc_usdt_swap/archive/20260409_193008/"},
                {"Prefix": "btc_usdt_swap/archive/20260405_141200/"},
                {"Prefix": "btc_usdt_swap/archive/20260401_120000/"},
            ],
        }

        versions = store.list_versions("btc_usdt_swap")

        assert versions == ["20260401_120000", "20260405_141200", "20260409_193008"]


class TestRollback:
    def test_rollback_copies_archive_to_latest(self, store, mock_s3):
        # List archive version files
        mock_s3.list_objects_v2.side_effect = [
            # First call: list archive files
            {
                "KeyCount": 2,
                "Contents": [
                    {"Key": "btc_usdt_swap/archive/20260409_193008/ensemble_0.pt"},
                    {"Key": "btc_usdt_swap/archive/20260409_193008/ensemble_config.json"},
                ],
            },
            # Second call: list current latest (for deletion)
            {
                "KeyCount": 1,
                "Contents": [{"Key": "btc_usdt_swap/latest/ensemble_0.pt"}],
            },
        ]

        store.rollback("btc_usdt_swap", "20260409_193008")

        copy_calls = mock_s3.copy_object.call_args_list
        assert len(copy_calls) == 2


class TestCleanupArchives:
    def test_cleanup_respects_retention_count(self, store, mock_s3):
        # 7 versions — should keep 5, delete 2 oldest
        prefixes = [
            {"Prefix": f"btc_usdt_swap/archive/2026040{i}_120000/"} for i in range(1, 8)
        ]
        mock_s3.list_objects_v2.side_effect = [
            # First call: list pair prefixes
            {"CommonPrefixes": [{"Prefix": "btc_usdt_swap/"}]},
            # Second call: list archive versions for btc
            {"CommonPrefixes": prefixes},
            # Third+ calls: list files in each version to delete
            {"Contents": [{"Key": f"btc_usdt_swap/archive/20260401_120000/ensemble_0.pt"}]},
            {"Contents": [{"Key": f"btc_usdt_swap/archive/20260402_120000/ensemble_0.pt"}]},
        ]

        store.cleanup_archives(retention_count=5, retention_days=999)

        delete_calls = mock_s3.delete_object.call_args_list
        assert len(delete_calls) == 2
