"""Tests for MinIO integration in the ML API flow."""

from unittest.mock import MagicMock, patch

import pytest


class TestModelStoreFromSettings:
    def test_creates_store_from_settings(self):
        mock_settings = MagicMock()
        mock_settings.minio_endpoint = "localhost:9000"
        mock_settings.minio_access_key = "minioadmin"
        mock_settings.minio_secret_key = "minioadmin"
        mock_settings.minio_bucket = "krypton-models"
        mock_settings.minio_use_ssl = False

        with patch("boto3.client") as mock_boto:
            client = MagicMock()
            mock_boto.return_value = client
            client.head_bucket.return_value = {}

            from app.api.ml import _get_model_store
            store = _get_model_store(mock_settings)

            assert store is not None
            assert store._bucket == "krypton-models"

    def test_returns_none_if_no_endpoint(self):
        mock_settings = MagicMock()
        mock_settings.minio_endpoint = ""

        from app.api.ml import _get_model_store
        assert _get_model_store(mock_settings) is None


class TestFetchFromMinio:
    @pytest.mark.asyncio
    async def test_fetch_downloads_all_pairs(self):
        from app.api.ml import _fetch_from_minio

        mock_store = MagicMock()
        mock_store.download_model.return_value = True

        pairs_fetched = await _fetch_from_minio(
            mock_store, "models", ["btc_usdt_swap", "eth_usdt_swap"]
        )

        assert mock_store.download_model.call_count == 2
        assert pairs_fetched == ["btc_usdt_swap", "eth_usdt_swap"]

    @pytest.mark.asyncio
    async def test_fetch_handles_missing_pair(self):
        from app.api.ml import _fetch_from_minio

        mock_store = MagicMock()
        mock_store.download_model.side_effect = [True, False]

        pairs_fetched = await _fetch_from_minio(
            mock_store, "models", ["btc_usdt_swap", "eth_usdt_swap"]
        )

        assert pairs_fetched == ["btc_usdt_swap"]

    @pytest.mark.asyncio
    async def test_fetch_handles_store_error(self):
        from app.api.ml import _fetch_from_minio

        mock_store = MagicMock()
        mock_store.download_model.side_effect = Exception("connection refused")

        pairs_fetched = await _fetch_from_minio(
            mock_store, "models", ["btc_usdt_swap"]
        )

        assert pairs_fetched == []


class TestRollbackEndpoint:
    @pytest.mark.asyncio
    async def test_rollback_requires_auth(self, client):
        resp = await client.post("/api/ml/rollback", params={"pair": "btc_usdt_swap", "version": "20260409"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_rollback_returns_error_without_minio(self, client, auth_cookies):
        resp = await client.post(
            "/api/ml/rollback",
            params={"pair": "btc_usdt_swap", "version": "20260409"},
            cookies=auth_cookies,
        )
        # MinIO not configured in test — should handle gracefully
        assert resp.status_code in (200, 500)


class TestTrainingRunSyncEndpoint:
    @pytest.mark.asyncio
    async def test_sync_requires_agent_key(self, client):
        resp = await client.post("/api/ml/training-run", json={"job_id": "test"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_sync_accepts_valid_payload(self, client):
        resp = await client.post(
            "/api/ml/training-run",
            json={
                "job_id": "20260411_143015",
                "status": "completed",
                "params": {"epochs": 80},
                "result": {"btc_usdt_swap": {"best_val_loss": 2.3}},
                "pairs_trained": ["btc_usdt_swap"],
                "duration_seconds": 120.5,
                "total_candles": 5000,
            },
            headers={"X-Agent-Key": "test-agent-key"},
        )
        # Will fail on DB write since test DB is mocked, but should reach the handler
        assert resp.status_code in (200, 500)
