import os
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from fastapi import FastAPI

from app.main import create_app

os.environ.setdefault("KRYPTON_API_KEY", "test-key")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")


@asynccontextmanager
async def _test_lifespan(app: FastAPI):
    mock_settings = MagicMock()
    mock_settings.krypton_api_key = "test-key"
    app.state.settings = mock_settings
    yield


@pytest.fixture
def app():
    return create_app(lifespan_override=_test_lifespan)


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
