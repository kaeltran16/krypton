# Google Authentication Design Spec

## Overview

Replace Krypton's static API key authentication with Google OAuth 2.0 + backend-issued JWT tokens. Single login method (Google only), gated by an email allowlist. The static `X-API-Key` mechanism is removed entirely.

## Decisions

- **Auth method**: Google OAuth only — no credentials, no API key fallback
- **Authorization**: Email allowlist via `ALLOWED_EMAILS` env var
- **Session**: Backend-issued JWT in httpOnly cookie, 30-day expiry
- **Rejection**: Silent "Access denied" for unauthorized Google accounts — no details leaked
- **Data isolation**: None — signals/settings are shared (single-user app), auth just gates access
- **Login UI**: Clean dark glass style matching app design tokens (see mockup v3)

## Auth Flow

```
User opens app
  → Frontend calls GET /api/auth/me
  → If 401 → show LoginScreen
  → User clicks "Continue with Google"
  → Google Identity Services renderButton → returns ID token via callback
  → Frontend POSTs ID token to POST /api/auth/google
  → Backend verifies ID token with Google (via asyncio.to_thread to avoid blocking event loop)
  → Backend checks email against ALLOWED_EMAILS
  → If not allowed → 403 "Access denied"
  → If allowed → upsert User row, issue JWT in httpOnly cookie
  → Frontend stores JWT in memory (for WebSocket use) → render app

Page refresh:
  → Frontend calls GET /api/auth/me (cookie sent automatically)
  → Backend returns user info + fresh JWT in response body
  → Frontend stores JWT in memory → WebSocket reconnects with token
```

Logout: `POST /api/auth/logout` → clears cookie.

WebSocket: JWT passed as query parameter on the WS URL (`/ws/signals?token=<jwt>`). The browser WebSocket API does not reliably send cross-origin cookies, so the existing query-param pattern (previously used for API key) is reused for JWT. Both `/api/auth/google` and `/api/auth/me` return the JWT in the response body so the frontend can store it in memory for WebSocket use (the httpOnly cookie is not readable via JS).

## Backend

### New Dependencies

- `PyJWT` — JWT encoding/decoding
- `google-auth` — Google ID token verification

### New Endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/auth/google` | None | Accept Google ID token, verify, check allowlist, issue JWT cookie |
| POST | `/api/auth/logout` | Authenticated | Clear JWT cookie |
| GET | `/api/auth/me` | Authenticated | Return current user info |

### Auth Dependency

Replace `require_settings_api_key` with `require_auth`:
- Read JWT from cookie
- Decode and validate (signature, expiry)
- Return user info or raise 401

All existing API routes and the WebSocket handshake switch to this dependency.

### JWT

- **Payload**: `{sub: user_id, email: email, exp: now + 30 days}`
- **Cookie config**: `httpOnly=True, secure=True, samesite="none", max_age=2592000` — `samesite="none"` required because frontend (Cloudflare Workers) and backend are on different origins. `secure=True` is mandatory with `samesite="none"`.
- **Signing**: HS256 with `JWT_SECRET` env var

### User Model

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK, server-default |
| email | String | unique, indexed |
| name | String | from Google profile |
| picture | String | nullable, Google avatar URL |
| created_at | DateTime | server default |
| last_login | DateTime | updated on each login |

No foreign keys added to existing tables — auth gates the entire app, not individual records.

### Migration

One Alembic migration to create `users` table. Runs automatically on container start via `entrypoint.sh`.

### Config Changes

**New env vars:**

| Variable | Purpose | Example |
|----------|---------|---------|
| `GOOGLE_CLIENT_ID` | Google OAuth client ID | `xxx.apps.googleusercontent.com` |
| `JWT_SECRET` | JWT signing key | random 64-char string |
| `ALLOWED_EMAILS` | Comma-separated email allowlist | `user@gmail.com` |
| `CORS_ORIGIN` | Production frontend origin for CORS | `https://app.example.com` |

**Removed:**

| Variable | Reason |
|----------|--------|
| `KRYPTON_API_KEY` | Replaced by Google OAuth |
| `VITE_API_KEY` | No longer needed |

### CORS

`CORSMiddleware` updated: `allow_credentials=True`, explicit `allow_origins` (no wildcards with credentials).

### Files Changed

- `backend/app/api/auth.py` — rewrite: Google verification, JWT issue/validate, login/logout/me endpoints
- `backend/app/config.py` — remove `krypton_api_key`, add `google_client_id`, `jwt_secret`, `allowed_emails`
- `backend/app/db/models.py` — add `User` model
- `backend/app/main.py` — remove API key from lifespan, update CORS config
- All API route files — swap `require_settings_api_key` for `require_auth`
- WebSocket handler — validate JWT from query parameter instead of API key
- `backend/app/api/auth.py` — also remove the old `require_api_key` function (unused after migration)

## Frontend

### New Files

- `web/src/features/auth/components/LoginScreen.tsx` — login screen (KRYPTON brand, glass card, dark glass Google button, encryption badge)
- `web/src/features/auth/hooks/useAuth.ts` — auth state: calls `/api/auth/me` on mount, exposes `{user, isLoading, isAuthenticated, login, logout}`

### Modified Files

- `web/src/App.tsx` — auth gate: `isLoading` → spinner, `!isAuthenticated` → LoginScreen, `isAuthenticated` → Layout
- `web/src/shared/lib/api.ts` — remove `X-API-Key` header, add `credentials: "include"`, add 401 handler (sets `isAuthenticated = false` → auth gate shows login screen; this also handles expired 30-day tokens gracefully — no refresh token flow, user simply re-authenticates)
- `web/src/shared/lib/constants.ts` — remove `VITE_API_KEY`
- WebSocket manager — replace API key query param with JWT token (stored in memory after login response, since cookie is httpOnly and not readable via JS)

### Google OAuth Integration

- Load Google Identity Services via script tag (`accounts.google.com/gsi/client`)
- Use `google.accounts.id.renderButton()` to render the sign-in button (reliable, works even when One Tap is suppressed by browser)
- Callback receives `credential` (ID token) → POST to `/api/auth/google`
- On success → backend returns JWT in both cookie (for REST) and response body (for WebSocket use) → store token in memory → app renders
- On page refresh → `GET /api/auth/me` returns user info + fresh JWT → store token in memory → WebSocket reconnects
- Login errors (403) shown inline below the button
- No npm dependencies added

### Login Screen Design

- Dark surface (#0a0f14) with subtle grid background and ambient cyan glow
- KRYPTON brand: cyan gradient icon (K), monospace name + tagline
- Glass card: "Authenticate / Authorized operators only"
- Google-rendered sign-in button via `renderButton()` (filled_black theme, large size)
- Error message in red (#F6465D) below button on auth failure
- Encryption badge: lock icon + "ENCRYPTED SESSION" in green (#56ef9f)
- 4px border radius throughout, Inter + JetBrains Mono typography

## Google Cloud Console Setup (Manual)

1. Create OAuth 2.0 Client ID (Web application type)
2. Add authorized JavaScript origins: `http://localhost:5173` (dev), production domain
3. Copy Client ID → `GOOGLE_CLIENT_ID` env var
4. Generate random 64-char string → `JWT_SECRET` env var
5. Set `ALLOWED_EMAILS` to authorized email(s)
