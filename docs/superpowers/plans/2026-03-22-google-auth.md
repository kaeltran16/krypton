# Google Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace static API key auth with Google OAuth 2.0 + backend JWT tokens, gated by email allowlist.

**Architecture:** Frontend loads Google Identity Services, gets an ID token on login, sends it to a new backend endpoint that verifies with Google, checks the email allowlist, and returns a JWT in an httpOnly cookie (+ response body for WebSocket use). All existing API routes switch from API key validation to JWT cookie validation. WebSocket passes JWT as a query parameter.

**Tech Stack:** PyJWT, google-auth (backend); Google Identity Services script tag (frontend)

**Spec:** `docs/superpowers/specs/2026-03-22-google-auth-design.md`

---

## File Map

### New Files

| File | Responsibility |
|------|---------------|
| `backend/app/api/auth.py` | Full rewrite — JWT encode/decode, Google ID token verification, auth dependency, login/logout/me endpoints |
| `backend/alembic/versions/xxxx_add_users_table.py` | Alembic migration for `users` table |
| `web/src/features/auth/components/LoginScreen.tsx` | Login UI — brand, glass card, Google button |
| `web/src/features/auth/hooks/useAuth.ts` | Auth state hook — check session, login, logout |

### Modified Files

| File | Changes |
|------|---------|
| `backend/app/config.py:36-38` | Remove `krypton_api_key`, add `google_client_id`, `jwt_secret`, `allowed_emails` |
| `backend/app/db/models.py:1-22` | Add `User` model after imports |
| `backend/app/main.py:1228-1234` | Update CORS — explicit origins, keep `allow_credentials=True` |
| `backend/app/api/ws.py:15-21` | Switch from API key to JWT token validation |
| `backend/app/api/routes.py:11,277` | Import and use new `require_auth` |
| `backend/app/api/account.py:7,40,51,59,100,168` | Switch to `require_auth` |
| `backend/app/api/alerts.py:10,130,188,206,249,274,308,338` | Switch to `require_auth` |
| `backend/app/api/backtest.py:14,107,143,155,316,330,343,355,369,385,401,539` | Switch to `require_auth` |
| `backend/app/api/candles.py:5,17` | Switch to `require_auth` |
| `backend/app/api/engine.py:12,26,189` | Switch to `require_auth` |
| `backend/app/api/ml.py:14,39,209,219,235,253,350` | Switch to `require_auth` |
| `backend/app/api/news.py:7,11` | Switch to `require_auth` |
| `backend/app/api/pipeline_settings.py:12,75,92` | Switch to `require_auth` |
| `backend/app/api/risk.py:9,46,60,81` | Switch to `require_auth` |
| `backend/tests/conftest.py:13-14,19-20` | Update test env vars and mock settings |
| `web/src/App.tsx` | Wrap in auth gate |
| `web/src/shared/lib/api.ts:1,68-78` | Remove API key, add `credentials: "include"`, add 401 handler |
| `web/src/shared/lib/constants.ts:7` | Remove `API_KEY` |
| `web/src/features/signals/hooks/useSignalWebSocket.ts:3,31-36` | Use JWT token instead of API key for WS |

---

## Task 1: Add User Model & Migration

**Files:**
- Modify: `backend/app/db/models.py` (add after line 22)
- Create: Alembic migration (auto-generated)

- [ ] **Step 1: Add User model to models.py**

Add after the `Base` import (line 22), before the `Candle` class:

```python
class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    picture: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    last_login: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
```

- [ ] **Step 2: Generate Alembic migration**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic revision --autogenerate -m "add users table"
```
Expected: New migration file created in `alembic/versions/`

- [ ] **Step 3: Run migration to verify it works**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic upgrade head
```
Expected: Migration applies successfully, `users` table created

---

## Task 2: Update Config — New Auth Settings

**Files:**
- Modify: `backend/app/config.py:36-38`
- Modify: `backend/.env` — remove `KRYPTON_API_KEY`, add new auth vars
- Modify: `backend/tests/test_config.py` — update for removed field

- [ ] **Step 1: Replace `krypton_api_key` with new auth settings in config.py**

Replace lines 37-38 in `Settings`:

```python
    # secrets (from .env)
    krypton_api_key: str
```

With:

```python
    # auth
    google_client_id: str = ""
    jwt_secret: str = "change-me-in-production"
    allowed_emails: str = ""  # comma-separated
```

- [ ] **Step 2: Update backend/.env file**

Remove the `KRYPTON_API_KEY=...` line. Add:
```
GOOGLE_CLIENT_ID=
JWT_SECRET=change-me-in-production
ALLOWED_EMAILS=
CORS_ORIGIN=
```

- [ ] **Step 3: Update test_config.py**

In `backend/tests/test_config.py`:

In `test_default_settings` (line 4-14): remove `monkeypatch.setenv("KRYPTON_API_KEY", "test-key")` and `assert settings.krypton_api_key == "test-key"`.

In `test_settings_with_yaml_override` (line 53-73): remove `monkeypatch.setenv("KRYPTON_API_KEY", "test-key")`.

- [ ] **Step 4: Verify the container starts with updated config**

Run:
```bash
docker compose up -d && docker compose logs --tail=20 krypton-api-1
```
Expected: App starts (may warn about missing google_client_id, but should not crash since defaults are empty strings)

---

## Task 3: Rewrite Auth Module — JWT + Google Verification + Endpoints

**Files:**
- Rewrite: `backend/app/api/auth.py`

- [ ] **Step 1: Write the new auth.py**

Replace the entire contents of `backend/app/api/auth.py` with:

```python
import asyncio
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from pydantic import BaseModel
from sqlalchemy import select

from app.db.models import User

router = APIRouter(prefix="/api/auth")

_ALGORITHM = "HS256"
_COOKIE_NAME = "krypton_token"
_TOKEN_EXPIRY_DAYS = 30


class GoogleLoginRequest(BaseModel):
    id_token: str


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    picture: str | None


def _decode_jwt(token: str, secret: str) -> dict:
    try:
        return jwt.decode(token, secret, algorithms=[_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")


def _encode_jwt(user_id: str, email: str, secret: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(days=_TOKEN_EXPIRY_DAYS),
    }
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)


def _set_cookie(response: Response, token: str):
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=_TOKEN_EXPIRY_DAYS * 86400,
    )


async def _get_current_user(request: Request) -> dict:
    token = request.cookies.get(_COOKIE_NAME)
    if not token:
        raise HTTPException(401, "Not authenticated")
    secret = request.app.state.settings.jwt_secret
    return _decode_jwt(token, secret)


def require_auth():
    return Depends(_get_current_user)


@router.post("/google")
async def google_login(body: GoogleLoginRequest, request: Request, response: Response):
    settings = request.app.state.settings

    # Verify the Google ID token (sync HTTP call — run off the event loop)
    try:
        idinfo = await asyncio.to_thread(
            google_id_token.verify_oauth2_token,
            body.id_token, google_requests.Request(), settings.google_client_id,
        )
    except ValueError:
        raise HTTPException(403, "Access denied")

    email = idinfo.get("email", "")
    allowed = [e.strip().lower() for e in settings.allowed_emails.split(",") if e.strip()]
    if email.lower() not in allowed:
        raise HTTPException(403, "Access denied")

    # Upsert user
    db = request.app.state.db
    async with db.session_factory() as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user:
            user.last_login = datetime.now(timezone.utc)
            user.name = idinfo.get("name", user.name)
            user.picture = idinfo.get("picture")
        else:
            user = User(
                email=email,
                name=idinfo.get("name", ""),
                picture=idinfo.get("picture"),
            )
            session.add(user)
        await session.commit()
        await session.refresh(user)

        token = _encode_jwt(str(user.id), user.email, settings.jwt_secret)
        _set_cookie(response, token)
        return {"token": token, "user": UserResponse(
            id=str(user.id), email=user.email, name=user.name, picture=user.picture
        )}


@router.post("/logout")
async def logout(response: Response, _user: dict = require_auth()):
    response.delete_cookie(key=_COOKIE_NAME, samesite="none", secure=True)
    return {"ok": True}


@router.get("/me")
async def me(request: Request, user: dict = require_auth()):
    settings = request.app.state.settings
    db = request.app.state.db
    async with db.session_factory() as session:
        result = await session.execute(select(User).where(User.email == user["email"]))
        db_user = result.scalar_one_or_none()
        if not db_user:
            raise HTTPException(401, "Not authenticated")
        token = _encode_jwt(str(db_user.id), db_user.email, settings.jwt_secret)
        return {
            "token": token,
            "user": UserResponse(
                id=str(db_user.id), email=db_user.email, name=db_user.name, picture=db_user.picture
            ),
        }
```

- [ ] **Step 2: Register the auth router in main.py**

In `backend/app/main.py`, add after the health endpoint (after line 1238):

```python
    from app.api.auth import router as auth_router
    app.include_router(auth_router)
```

- [ ] **Step 3: Add PyJWT and google-auth to requirements and rebuild**

Add to `backend/requirements.txt`:
```
PyJWT
google-auth
```

Then rebuild the container:
```bash
docker compose build api && docker compose up -d
```
Expected: Container rebuilds and starts successfully with new dependencies

---

## Task 4: Switch All API Routes from API Key to JWT Auth

**Files:**
- Modify: All route files in `backend/app/api/` that import `require_settings_api_key`

The change is mechanical — every file follows the same pattern:

1. Change `from app.api.auth import require_settings_api_key` → `from app.api.auth import require_auth`
2. Change every `require_settings_api_key()` → `require_auth()`
3. Change type annotations from `_key: str = ...` → `_user: dict = ...` (since `require_auth` returns a dict, not a string)

- [ ] **Step 1: Update routes.py**

In `backend/app/api/routes.py`:
- Line 11: `from app.api.auth import require_settings_api_key` → `from app.api.auth import require_auth`
- Line 277: `auth = require_settings_api_key()` → `auth = require_auth()`

- [ ] **Step 2: Update account.py**

In `backend/app/api/account.py`:
- Line 7: `from app.api.auth import require_settings_api_key` → `from app.api.auth import require_auth`
- Replace all `require_settings_api_key()` with `require_auth()` (lines 40, 51, 59, 100, 168)

- [ ] **Step 3: Update alerts.py**

In `backend/app/api/alerts.py`:
- Line 10: change import
- Replace all `require_settings_api_key()` → `require_auth()` (lines 130, 188, 206, 249, 274, 308, 338)

- [ ] **Step 4: Update backtest.py**

In `backend/app/api/backtest.py`:
- Line 14: change import
- Replace all `require_settings_api_key()` → `require_auth()` (lines 107, 143, 155, 316, 330, 343, 355, 369, 385, 401, 539)

- [ ] **Step 5: Update candles.py**

In `backend/app/api/candles.py`:
- Line 5: change import
- Line 17: `require_settings_api_key()` → `require_auth()`

- [ ] **Step 6: Update engine.py**

In `backend/app/api/engine.py`:
- Line 12: change import
- Lines 26, 189: `require_settings_api_key()` → `require_auth()`

- [ ] **Step 7: Update ml.py**

In `backend/app/api/ml.py`:
- Line 14: change import
- Replace all `require_settings_api_key()` → `require_auth()` (lines 39, 209, 219, 235, 253, 350)

- [ ] **Step 8: Update news.py**

In `backend/app/api/news.py`:
- Line 7: change import
- Line 11: `auth = require_settings_api_key()` → `auth = require_auth()`

- [ ] **Step 9: Update pipeline_settings.py**

In `backend/app/api/pipeline_settings.py`:
- Line 12: change import
- Lines 75, 92: `require_settings_api_key()` → `require_auth()`

- [ ] **Step 10: Update risk.py**

In `backend/app/api/risk.py`:
- Line 9: change import
- Lines 46, 60, 81: `require_settings_api_key()` → `require_auth()`

- [ ] **Step 11: Update WebSocket handler (ws.py)**

In `backend/app/api/ws.py`, replace lines 14-21:

```python
@router.websocket("/ws/signals")
async def signal_stream(websocket: WebSocket, api_key: str | None = None):
    settings = websocket.app.state.settings
    client_key = api_key or websocket.headers.get("x-api-key")
    if client_key != settings.krypton_api_key:
        await websocket.accept()
        await websocket.close(code=4001, reason="Invalid API key")
        return
```

With:

```python
@router.websocket("/ws/signals")
async def signal_stream(websocket: WebSocket, token: str | None = None):
    if not token:
        await websocket.accept()
        await websocket.close(code=4001, reason="Not authenticated")
        return
    try:
        jwt.decode(token, websocket.app.state.settings.jwt_secret, algorithms=["HS256"])
    except jwt.InvalidTokenError:
        await websocket.accept()
        await websocket.close(code=4001, reason="Invalid token")
        return
```

Also add import at top of `ws.py`:
```python
import jwt
```

---

## Task 5: Update CORS & Clean Up main.py

**Files:**
- Modify: `backend/app/main.py:1228-1234`

- [ ] **Step 1: Update CORS middleware**

Replace lines 1228-1234 in `main.py`:

```python
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
```

With:

```python
    allowed_origins = [
        "http://localhost:5173",
        "http://localhost:4173",
    ]
    # Add production origin from env if set
    prod_origin = os.environ.get("CORS_ORIGIN")
    if prod_origin:
        allowed_origins.append(prod_origin)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
```

Make sure `import os` is at the top of `main.py` (it should already be there).

- [ ] **Step 2: Verify container starts**

Run:
```bash
docker compose up -d && docker compose logs --tail=10 krypton-api-1
```
Expected: No errors

---

## Task 6: Update Test Configuration & All Test Files

**Files:**
- Modify: `backend/tests/conftest.py`
- Rewrite: `backend/tests/api/test_auth.py` — old tests are for removed API key auth, replace with JWT auth tests
- Modify: `backend/tests/api/test_ws.py` — WebSocket tests use `api_key` query param, switch to `token`
- Modify (mechanical — change headers to cookies): All files below that use `headers={"X-API-Key": ...}` or `mock_settings.krypton_api_key`:
  - `backend/tests/api/test_routes.py`
  - `backend/tests/api/test_account.py`
  - `backend/tests/api/test_backtest.py`
  - `backend/tests/api/test_journal.py`
  - `backend/tests/api/test_ml.py`
  - `backend/tests/api/test_pipeline_settings.py`
  - `backend/tests/api/test_tuning.py`
  - `backend/tests/api/test_engine_params.py`
  - `backend/tests/api/test_engine_apply.py`
  - `backend/tests/api/test_optimize_endpoints.py`
  - `backend/tests/api/test_news_endpoints.py`
  - `backend/tests/api/test_signal_stats.py`
  - `backend/tests/test_alert_api.py`

- [ ] **Step 1: Update conftest.py**

Replace lines 13-14:
```python
os.environ.setdefault("KRYPTON_API_KEY", "test-key")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
```

With:
```python
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("ALLOWED_EMAILS", "test@example.com")
```

Replace line 20:
```python
    mock_settings.krypton_api_key = "test-key"
```

With:
```python
    mock_settings.jwt_secret = "test-jwt-secret"
    mock_settings.google_client_id = "test-client-id"
    mock_settings.allowed_emails = "test@example.com"
```

- [ ] **Step 2: Add a helper to generate test JWTs and an auth_cookies fixture**

Add after the imports in `conftest.py`:

```python
import jwt as pyjwt

def make_test_jwt(email: str = "test@example.com", user_id: str = "00000000-0000-0000-0000-000000000001"):
    from datetime import datetime, timedelta, timezone
    payload = {"sub": user_id, "email": email, "exp": datetime.now(timezone.utc) + timedelta(days=1)}
    return pyjwt.encode(payload, "test-jwt-secret", algorithm="HS256")
```

Add after the `client` fixture:

```python
@pytest.fixture
def auth_cookies():
    token = make_test_jwt()
    return {"krypton_token": token}
```

- [ ] **Step 3: Rewrite test_auth.py**

Delete all existing content and replace with tests for the new JWT auth:

```python
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
async def test_google_login_allowed_email(client, monkeypatch):
    """Happy path: valid Google ID token with an allowed email → 200 + cookie + token."""
    import asyncio
    from unittest.mock import patch

    fake_idinfo = {"email": "test@example.com", "name": "Test User", "picture": None}

    async def fake_verify(*args, **kwargs):
        return fake_idinfo

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
```

- [ ] **Step 4: Update test_ws.py WebSocket tests**

Replace `api_key=test-key` query params with `token=<jwt>`:

In `test_websocket_connects_and_receives_subscription` (line 73):
```python
        with client.websocket_connect(f"/ws/signals?token={make_test_jwt()}") as ws:
```

In `test_websocket_handles_malformed_json` (line 81):
```python
        with client.websocket_connect(f"/ws/signals?token={make_test_jwt()}") as ws:
```

Remove `test_websocket_accepts_header_api_key` entirely (lines 86-91) — header auth is no longer supported.

Add import at top: `from tests.conftest import make_test_jwt`

- [ ] **Step 5: Mechanical update of all remaining test files**

For every file listed above, apply these two transformations:

**Pattern 1 — headers to cookies:** Every occurrence of:
```python
headers={"X-API-Key": "test-key"}
```
Change to:
```python
cookies={"krypton_token": make_test_jwt()}
```
And add `from tests.conftest import make_test_jwt` to the imports.

**Pattern 2 — mock settings:** Every occurrence of:
```python
mock_settings.krypton_api_key = "test-key"
```
Change to:
```python
mock_settings.jwt_secret = "test-jwt-secret"
```

Files and approximate occurrence counts:
- `test_routes.py` — headers pattern (~5 occurrences)
- `test_account.py` — headers pattern (~5 occurrences)
- `test_backtest.py` — headers + mock_settings patterns
- `test_journal.py` — headers pattern
- `test_ml.py` — headers + mock_settings patterns
- `test_pipeline_settings.py` — headers + mock_settings patterns
- `test_tuning.py` — headers + mock_settings patterns
- `test_engine_params.py` — headers + mock_settings patterns
- `test_engine_apply.py` — headers + mock_settings patterns
- `test_optimize_endpoints.py` — headers + mock_settings patterns
- `test_news_endpoints.py` — headers + mock_settings patterns (~6 occurrences)
- `test_signal_stats.py` — headers + mock_settings patterns
- `test_alert_api.py` — headers + mock_settings patterns

- [ ] **Step 6: Run all tests to verify**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest -x -q
```
Expected: All tests pass

---

## Task 7: Frontend — Auth Hook & API Client Updates

**Files:**
- Create: `web/src/features/auth/hooks/useAuth.ts`
- Modify: `web/src/shared/lib/api.ts`
- Modify: `web/src/shared/lib/constants.ts`

- [ ] **Step 1: Remove API_KEY from constants.ts**

In `web/src/shared/lib/constants.ts`, delete line 7:
```typescript
export const API_KEY = import.meta.env.VITE_API_KEY ?? "";
```

- [ ] **Step 2: Update api.ts — remove API key, add credentials, add 401 handling**

In `web/src/shared/lib/api.ts`:

Replace line 1:
```typescript
import { API_BASE_URL, API_KEY } from "./constants";
```
With:
```typescript
import { API_BASE_URL } from "./constants";
```

Replace lines 68-79:
```typescript
export const jsonHeaders: HeadersInit = {
  "Content-Type": "application/json",
  ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, { headers: jsonHeaders, ...init });
  if (!res.ok) {
    throw new Error(`API ${res.status}: ${res.statusText}`);
  }
  return res.json();
}
```

With:
```typescript
export const jsonHeaders: HeadersInit = {
  "Content-Type": "application/json",
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: jsonHeaders,
    credentials: "include",
    ...init,
  });
  if (res.status === 401) {
    window.dispatchEvent(new Event("auth:unauthorized"));
    throw new Error("Unauthorized");
  }
  if (!res.ok) {
    throw new Error(`API ${res.status}: ${res.statusText}`);
  }
  return res.json();
}
```

- [ ] **Step 3: Add auth API methods to api.ts**

Add to the `api` object (near the top of the methods):

```typescript
  // Auth
  authMe: () => request<{ token: string; user: { id: string; email: string; name: string; picture: string | null } }>("/api/auth/me"),
  authGoogle: (idToken: string) => request<{ token: string; user: { id: string; email: string; name: string; picture: string | null } }>("/api/auth/google", {
    method: "POST",
    body: JSON.stringify({ id_token: idToken }),
  }),
  authLogout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
```

- [ ] **Step 4: Create useAuth hook**

Create `web/src/features/auth/hooks/useAuth.ts`:

```typescript
import { useState, useEffect, useCallback } from "react";
import { api } from "../../../shared/lib/api";

interface AuthUser {
  id: string;
  email: string;
  name: string;
  picture: string | null;
}

// In-memory JWT token for WebSocket auth (cookie is httpOnly, can't read from JS)
let wsToken: string | null = null;
export function getWsToken() { return wsToken; }

export function useAuth() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const checkAuth = useCallback(async () => {
    try {
      const res = await api.authMe();
      wsToken = res.token;
      setUser(res.user);
    } catch {
      setUser(null);
      wsToken = null;
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    checkAuth();

    const handleUnauthorized = () => {
      setUser(null);
      wsToken = null;
    };
    window.addEventListener("auth:unauthorized", handleUnauthorized);
    return () => window.removeEventListener("auth:unauthorized", handleUnauthorized);
  }, [checkAuth]);

  const login = useCallback(async (googleIdToken: string) => {
    const { token, user: userData } = await api.authGoogle(googleIdToken);
    wsToken = token;
    setUser(userData);
  }, []);

  const logout = useCallback(async () => {
    await api.authLogout();
    setUser(null);
    wsToken = null;
  }, []);

  return {
    user,
    isLoading,
    isAuthenticated: !!user,
    login,
    logout,
  };
}
```

---

## Task 8: Frontend — Login Screen Component

**Files:**
- Create: `web/src/features/auth/components/LoginScreen.tsx`

- [ ] **Step 1: Create LoginScreen.tsx**

Create `web/src/features/auth/components/LoginScreen.tsx`:

```tsx
import { useState, useEffect, useRef, useCallback } from "react";

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID ?? "";

interface LoginScreenProps {
  onLogin: (idToken: string) => Promise<void>;
}

export function LoginScreen({ onLogin }: LoginScreenProps) {
  const googleBtnRef = useRef<HTMLDivElement>(null);
  const googleLoadedRef = useRef(false);
  const loginInProgress = useRef(false);
  const [error, setError] = useState<string | null>(null);

  const handleCredentialResponse = useCallback(
    async (response: { credential: string }) => {
      if (loginInProgress.current) return;
      loginInProgress.current = true;
      setError(null);
      try {
        await onLogin(response.credential);
      } catch {
        setError("Access denied. Contact an administrator.");
        loginInProgress.current = false;
      }
    },
    [onLogin],
  );

  useEffect(() => {
    if (googleLoadedRef.current) return;
    googleLoadedRef.current = true;

    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.onload = () => {
      const g = (window as any).google.accounts.id;
      g.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: handleCredentialResponse,
      });
      // Render Google's own sign-in button (reliable, works even when One Tap is suppressed)
      if (googleBtnRef.current) {
        g.renderButton(googleBtnRef.current, {
          type: "standard",
          theme: "filled_black",
          size: "large",
          width: 280,
          text: "continue_with",
        });
      }
    };
    document.head.appendChild(script);
  }, [handleCredentialResponse]);

  return (
    <div className="min-h-dvh flex flex-col items-center justify-center bg-[#0a0f14] relative overflow-hidden">
      {/* Grid background */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          backgroundImage:
            "linear-gradient(rgba(105,218,255,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(105,218,255,0.03) 1px, transparent 1px)",
          backgroundSize: "40px 40px",
        }}
      />

      {/* Ambient glow */}
      <div className="absolute top-1/3 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[300px] h-[300px] rounded-full bg-[radial-gradient(circle,rgba(0,207,252,0.08)_0%,transparent_70%)] pointer-events-none" />

      <div className="relative z-10 w-[320px] flex flex-col items-center gap-10">
        {/* Brand */}
        <div className="flex flex-col items-center gap-3">
          <div className="w-14 h-14 rounded bg-gradient-to-br from-[#00cffc] to-[#69daff] flex items-center justify-center font-mono font-bold text-2xl text-[#0a0f14] shadow-[0_0_24px_rgba(0,207,252,0.15)]">
            K
          </div>
          <span className="font-mono text-[1.75rem] font-bold tracking-[0.15em] text-[#e7ebf3]">
            KRYPTON
          </span>
          <span className="font-mono text-[0.6875rem] text-[#71767d] tracking-[0.08em]">
            SIGNAL ENGINE v2.0
          </span>
        </div>

        {/* Login card */}
        <div className="w-full glass-card rounded p-8 flex flex-col gap-6">
          <div className="text-center">
            <h2 className="text-base font-semibold text-[#e7ebf3] mb-1">
              Authenticate
            </h2>
            <p className="text-[0.8125rem] text-[#71767d]">
              Authorized operators only
            </p>
          </div>

          {/* Google sign-in button (rendered by GIS SDK — reliable across browsers) */}
          <div className="flex justify-center">
            <div ref={googleBtnRef} />
          </div>

          {/* Error message */}
          {error && (
            <p className="text-center text-[0.8125rem] text-[#F6465D]">
              {error}
            </p>
          )}

          {/* Divider */}
          <div className="flex items-center gap-4">
            <div className="flex-1 h-px bg-[rgba(67,72,79,0.3)]" />
            <span className="font-mono text-[0.625rem] text-[#71767d] tracking-[0.1em]">
              SECURE_AUTH
            </span>
            <div className="flex-1 h-px bg-[rgba(67,72,79,0.3)]" />
          </div>

          {/* Encryption badge */}
          <div className="flex items-center justify-center gap-2 font-mono text-[0.5625rem] text-[#56ef9f] tracking-[0.05em] opacity-60">
            <svg
              width="12"
              height="12"
              viewBox="0 0 24 24"
              fill="none"
              stroke="#56ef9f"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
              <path d="M7 11V7a5 5 0 0 1 10 0v4" />
            </svg>
            ENCRYPTED SESSION
          </div>
        </div>
      </div>
    </div>
  );
}
```

---

## Task 9: Frontend — Auth Gate in App.tsx & WebSocket Update

**Files:**
- Modify: `web/src/App.tsx`
- Modify: `web/src/features/signals/hooks/useSignalWebSocket.ts`

- [ ] **Step 1: Wrap App.tsx in auth gate**

Replace the entire `web/src/App.tsx` with:

```tsx
import { useState, useEffect } from "react";
import { Layout } from "./shared/components/Layout";
import { HomeView } from "./features/home/components/HomeView";
import { ChartView } from "./features/chart/components/ChartView";
import { SignalsView } from "./features/signals/components/SignalsView";
import { NewsView } from "./features/news/components/NewsView";
import { NewsAlertToast } from "./features/news/components/NewsAlertToast";
import { AlertToast } from "./features/alerts/components/AlertToast";
import { MorePage } from "./features/more/components/MorePage";
import { useSignalWebSocket } from "./features/signals/hooks/useSignalWebSocket";
import { useLivePrice } from "./shared/hooks/useLivePrice";
import { AVAILABLE_PAIRS } from "./shared/lib/constants";
import { useSettingsStore } from "./features/settings/store";
import { useServiceWorker } from "./shared/hooks/useServiceWorker";
import { UpdateModal } from "./shared/components/UpdateModal";
import { useAuth } from "./features/auth/hooks/useAuth";
import { LoginScreen } from "./features/auth/components/LoginScreen";

export default function App() {
  const { user, isLoading, isAuthenticated, login, logout } = useAuth();

  if (isLoading) {
    return (
      <div className="min-h-dvh flex items-center justify-center bg-[#0a0f14]">
        <div className="w-8 h-8 border-2 border-[#69daff] border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!isAuthenticated) {
    return <LoginScreen onLogin={login} />;
  }

  return <AuthenticatedApp />;
}

function AuthenticatedApp() {
  const [selectedPair, setSelectedPair] = useState<string>(AVAILABLE_PAIRS[0]);
  useSignalWebSocket();

  useEffect(() => {
    useSettingsStore.getState().fetchFromServer();
  }, []);
  const { price, change24h } = useLivePrice(selectedPair);
  const { showUpdateModal, applyUpdate, dismiss } = useServiceWorker();

  return (
    <>
      <NewsAlertToast />
      <AlertToast />
      {showUpdateModal && <UpdateModal onUpdate={applyUpdate} onDismiss={dismiss} />}
      <Layout
        home={<HomeView />}
        chart={<ChartView pair={selectedPair} />}
        signals={<SignalsView />}
        news={<NewsView />}
        more={<MorePage />}
        price={price}
        change24h={change24h}
        selectedPair={selectedPair}
        onPairChange={setSelectedPair}
      />
    </>
  );
}
```

- [ ] **Step 2: Update useSignalWebSocket to use JWT token**

In `web/src/features/signals/hooks/useSignalWebSocket.ts`:

Replace line 3:
```typescript
import { WS_BASE_URL, API_KEY } from "../../../shared/lib/constants";
```
With:
```typescript
import { WS_BASE_URL } from "../../../shared/lib/constants";
import { getWsToken } from "../../auth/hooks/useAuth";
```

Replace lines 31-36:
```typescript
    const params = new URLSearchParams();
    if (API_KEY) params.set("api_key", API_KEY);
    const qs = params.toString();

    const ws = new WebSocketManager(
      `${WS_BASE_URL}/ws/signals${qs ? `?${qs}` : ""}`,
    );
```

With:
```typescript
    const token = getWsToken();
    const params = new URLSearchParams();
    if (token) params.set("token", token);
    const qs = params.toString();

    const ws = new WebSocketManager(
      `${WS_BASE_URL}/ws/signals${qs ? `?${qs}` : ""}`,
    );
```

- [ ] **Step 3: Run frontend build to verify no type errors**

Run:
```bash
cd web && pnpm build
```
Expected: Build succeeds with no errors

---

## Task 10: Add VITE_GOOGLE_CLIENT_ID to Frontend Config

**Files:**
- Modify: `web/.env` or `web/.env.example`

- [ ] **Step 1: Add VITE_GOOGLE_CLIENT_ID to env**

Add to `web/.env` (or create `.env.example`):
```
VITE_GOOGLE_CLIENT_ID=your-google-client-id-here.apps.googleusercontent.com
```

- [ ] **Step 2: Remove VITE_API_KEY from env**

Remove the `VITE_API_KEY=...` line from `web/.env`.

---

## Task 11: End-to-End Verification

- [ ] **Step 1: Ensure backend starts cleanly**

Run:
```bash
docker compose up -d && docker compose logs --tail=30 krypton-api-1
```
Expected: No errors, app factory creates successfully

- [ ] **Step 2: Run backend tests**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest -x -q
```
Expected: All tests pass

- [ ] **Step 3: Run frontend build**

Run:
```bash
cd web && pnpm build
```
Expected: Build succeeds

- [ ] **Step 4: Run frontend tests**

Run:
```bash
cd web && pnpm test
```
Expected: Tests pass (any tests referencing API_KEY may need updating)

- [ ] **Step 5: Manual smoke test**

1. Start `pnpm dev` and open the app
2. Verify login screen shows (not the app)
3. Verify Google button loads (requires valid `VITE_GOOGLE_CLIENT_ID`)
4. After Google login, verify app loads normally
5. Verify WebSocket connects (signals feed works)
6. Verify logout returns to login screen

- [ ] **Step 6: Final commit (squash if preferred)**

```bash
git add -A
git commit -m "feat(auth): complete google oauth implementation with jwt sessions"
```
