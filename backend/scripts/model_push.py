#!/usr/bin/env python3
"""Push locally trained ML models to MinIO on the prod droplet.

Usage:
    python scripts/model_push.py --all
    python scripts/model_push.py --pair btc_usdt_swap
    python scripts/model_push.py --regime
    python scripts/model_push.py --all --sync-run 20260411_143015

Environment variables (or .env file):
    MINIO_ENDPOINT    — e.g., yourdomain.com/minio (external) or localhost:9000 (dev)
    MINIO_ACCESS_KEY  — MinIO access key
    MINIO_SECRET_KEY  — MinIO secret key
    MINIO_USE_SSL     — "true" for HTTPS (default: "false")
    MINIO_BUCKET      — bucket name (default: "krypton-models")
    PROD_API_URL      — e.g., https://yourdomain.com (for reload trigger)
    AGENT_API_KEY     — X-Agent-Key for API auth
    ML_CHECKPOINT_DIR — local models directory (default: "models")
"""

import argparse
import json
import os
import sys

# Add parent dir to path so we can import app modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import httpx


def get_env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def main():
    parser = argparse.ArgumentParser(description="Push ML models to MinIO")
    parser.add_argument("--all", action="store_true", help="Push all pairs")
    parser.add_argument("--pair", type=str, help="Push a specific pair slug")
    parser.add_argument("--regime", action="store_true", help="Push regime classifier")
    parser.add_argument("--sync-run", type=str, help="Sync a training run by job_id")
    parser.add_argument("--no-reload", action="store_true", help="Skip reload trigger")
    args = parser.parse_args()

    if not (args.all or args.pair or args.regime):
        parser.error("Specify --all, --pair, or --regime")

    # Config from env
    endpoint = get_env("MINIO_ENDPOINT", "localhost:9000")
    access_key = get_env("MINIO_ACCESS_KEY", "minioadmin")
    secret_key = get_env("MINIO_SECRET_KEY", "minioadmin")
    bucket = get_env("MINIO_BUCKET", "krypton-models")
    use_ssl = get_env("MINIO_USE_SSL", "false").lower() == "true"
    checkpoint_dir = get_env("ML_CHECKPOINT_DIR", "models")
    api_url = get_env("PROD_API_URL", "")
    agent_key = get_env("AGENT_API_KEY", "")

    from app.ml.model_store import ModelStore

    print(f"Connecting to MinIO at {endpoint}...")
    store = ModelStore(
        endpoint=endpoint,
        access_key=access_key,
        secret_key=secret_key,
        bucket=bucket,
        use_ssl=use_ssl,
    )

    pairs_pushed = []

    if args.all:
        if not os.path.isdir(checkpoint_dir):
            print(f"Checkpoint dir {checkpoint_dir} not found")
            sys.exit(1)
        for entry in sorted(os.listdir(checkpoint_dir)):
            pair_dir = os.path.join(checkpoint_dir, entry)
            config_path = os.path.join(pair_dir, "ensemble_config.json")
            if os.path.isdir(pair_dir) and os.path.isfile(config_path):
                print(f"Uploading {entry}...")
                ts = store.upload_model(entry, pair_dir)
                print(f"  -> archived as {ts}")
                pairs_pushed.append(entry)

    if args.pair:
        pair_dir = os.path.join(checkpoint_dir, args.pair)
        if not os.path.isdir(pair_dir):
            print(f"Pair dir {pair_dir} not found")
            sys.exit(1)
        print(f"Uploading {args.pair}...")
        ts = store.upload_model(args.pair, pair_dir)
        print(f"  -> archived as {ts}")
        pairs_pushed.append(args.pair)

    if args.regime:
        regime_dir = os.path.join(checkpoint_dir, "regime")
        if not os.path.isdir(regime_dir):
            print(f"Regime dir {regime_dir} not found")
            sys.exit(1)
        print("Uploading regime classifier...")
        ts = store.upload_model("regime", regime_dir)
        print(f"  -> archived as {ts}")

    # Sync training run metadata
    if args.sync_run and api_url and agent_key:
        run_path = os.path.join(checkpoint_dir, ".last_training_run.json")
        if os.path.isfile(run_path):
            with open(run_path) as f:
                run_data = json.load(f)
            print(f"Syncing training run {args.sync_run}...")
            resp = httpx.post(
                f"{api_url}/api/ml/training-run",
                json=run_data,
                headers={"X-Agent-Key": agent_key},
                timeout=10,
            )
            print(f"  -> {resp.status_code}: {resp.json()}")

    # Trigger reload
    if not args.no_reload and api_url and agent_key and pairs_pushed:
        print("Triggering model reload...")
        resp = httpx.post(
            f"{api_url}/api/ml/reload-agent",
            headers={"X-Agent-Key": agent_key},
            timeout=30,
        )
        print(f"  -> {resp.status_code}: {resp.json()}")

    print(f"\nDone. Pushed: {pairs_pushed or ['regime']}")


if __name__ == "__main__":
    main()
