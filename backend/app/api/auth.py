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

ALGORITHM = "HS256"
_COOKIE_NAME = "krypton_token"
_TOKEN_EXPIRY_DAYS = 30
_WS_TOKEN_EXPIRY_MINUTES = 5


class GoogleLoginRequest(BaseModel):
    id_token: str


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    picture: str | None


def _decode_jwt(token: str, secret: str) -> dict:
    try:
        return jwt.decode(token, secret, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")


def _encode_jwt(user_id: str, email: str, secret: str, name: str = "", picture: str | None = None) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "name": name,
        "picture": picture,
        "exp": datetime.now(timezone.utc) + timedelta(days=_TOKEN_EXPIRY_DAYS),
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def create_ws_token(secret: str) -> str:
    """Create a short-lived JWT for WebSocket authentication."""
    payload = {
        "purpose": "ws",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=_WS_TOKEN_EXPIRY_MINUTES),
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def verify_ws_token(token: str, secret: str) -> bool:
    """Verify a WS token has valid signature, expiry, and purpose claim."""
    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
        return payload.get("purpose") == "ws"
    except jwt.InvalidTokenError:
        return False


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


async def _verify_agent_key(request: Request) -> dict:
    key = request.headers.get("X-Agent-Key")
    if not key:
        raise HTTPException(401, "Agent key required")
    if key != request.app.state.settings.agent_api_key:
        raise HTTPException(403, "Invalid agent key")
    return {"agent": True}


def require_agent_key():
    return Depends(_verify_agent_key)


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

        token = _encode_jwt(str(user.id), user.email, settings.jwt_secret, user.name, user.picture)
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
    secret = request.app.state.settings.jwt_secret
    token = _encode_jwt(user["sub"], user["email"], secret, user.get("name", ""), user.get("picture"))
    return {
        "token": token,
        "user": UserResponse(
            id=user["sub"], email=user["email"], name=user.get("name", ""), picture=user.get("picture")
        ),
    }


@router.post("/ws-token")
async def get_ws_token(request: Request, _user: dict = require_auth()):
    """Return a short-lived JWT for WebSocket authentication."""
    secret = request.app.state.settings.jwt_secret
    return {"token": create_ws_token(secret)}
