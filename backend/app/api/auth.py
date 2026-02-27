from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

_AUTH_ERROR = HTTPException(status_code=401, detail="Invalid or missing API key")


def _validate_key(key: str | None, expected: str):
    if not key or key != expected:
        raise _AUTH_ERROR
    return key


def require_api_key(expected_key: str):
    async def verify(key: str = Security(api_key_header)):
        return _validate_key(key, expected_key)
    return Depends(verify)


def require_settings_api_key():
    async def verify(request: Request, key: str = Security(api_key_header)):
        return _validate_key(key, request.app.state.settings.krypton_api_key)
    return Depends(verify)
