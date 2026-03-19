"""Test POST /api/engine/apply endpoint."""

import asyncio
import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import MagicMock, AsyncMock

HEADERS = {"X-API-Key": "test-key"}


@pytest.mark.asyncio
async def test_preview_returns_diff(client):
    resp = await client.post(
        "/api/engine/apply",
        headers=HEADERS,
        json={
            "changes": {"blending.thresholds.signal": 35},
            "confirm": False,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["preview"] is True
    assert len(data["diff"]) == 1
    assert data["diff"][0]["path"] == "blending.thresholds.signal"
    assert data["diff"][0]["current"] == 40
    assert data["diff"][0]["proposed"] == 35


@pytest.mark.asyncio
async def test_preview_is_default(client):
    resp = await client.post(
        "/api/engine/apply",
        headers=HEADERS,
        json={"changes": {"blending.thresholds.signal": 35}},
    )
    assert resp.status_code == 200
    assert resp.json()["preview"] is True


@pytest.mark.asyncio
async def test_empty_changes_rejected(client):
    resp = await client.post(
        "/api/engine/apply",
        headers=HEADERS,
        json={"changes": {}},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_unknown_dot_path_returns_unknown_source(client):
    """Unknown dot-paths are included in diff with source 'unknown'."""
    resp = await client.post(
        "/api/engine/apply",
        headers=HEADERS,
        json={
            "changes": {"nonexistent.path": 42},
            "confirm": False,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["diff"][0]["source"] == "unknown"
    assert data["diff"][0]["current"] is None
