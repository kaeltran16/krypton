import pytest
from httpx import ASGITransport, AsyncClient
from tests.conftest import make_test_jwt


@pytest.mark.asyncio
async def test_me_returns_401_without_cookie(client):
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_returns_401_with_invalid_jwt(client):
    resp = await client.get("/api/auth/me", cookies={"krypton_token": "invalid-token"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_returns_401_with_expired_jwt(client):
    import jwt as pyjwt
    from datetime import datetime, timedelta, timezone
    expired = pyjwt.encode(
        {"sub": "test", "email": "test@example.com", "exp": datetime.now(timezone.utc) - timedelta(days=1)},
        "test-jwt-secret", algorithm="HS256"
    )
    resp = await client.get("/api/auth/me", cookies={"krypton_token": expired})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_logout_clears_cookie(client, auth_cookies):
    resp = await client.post("/api/auth/logout", cookies=auth_cookies)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_google_login_allowed_email(app, client):
    """Happy path: valid Google ID token with an allowed email → 200 + cookie + token."""
    import uuid
    from unittest.mock import patch, AsyncMock, MagicMock
    from app.db.models import User

    fake_idinfo = {"email": "test@example.com", "name": "Test User", "picture": None}

    async def fake_verify(*args, **kwargs):
        return fake_idinfo

    # Mock DB session for user upsert
    fake_user = User(
        id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        email="test@example.com",
        name="Test User",
        picture=None,
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None  # new user

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock(side_effect=lambda u: setattr(u, 'id', fake_user.id))
    mock_session.add = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_db = MagicMock()
    mock_db.session_factory = MagicMock(return_value=mock_session)
    app.state.db = mock_db

    with patch("app.api.auth.asyncio.to_thread", side_effect=fake_verify):
        resp = await client.post("/api/auth/google", json={"id_token": "fake-token"})
    assert resp.status_code == 200
    body = resp.json()
    assert "token" in body
    assert body["user"]["email"] == "test@example.com"


@pytest.mark.asyncio
async def test_google_login_disallowed_email(client):
    """Valid Google token but email not in allowlist → 403."""
    import asyncio
    from unittest.mock import patch

    fake_idinfo = {"email": "hacker@evil.com", "name": "Hacker", "picture": None}

    async def fake_verify(*args, **kwargs):
        return fake_idinfo

    with patch("app.api.auth.asyncio.to_thread", side_effect=fake_verify):
        resp = await client.post("/api/auth/google", json={"id_token": "fake-token"})
    assert resp.status_code == 403
