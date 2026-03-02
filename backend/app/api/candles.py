import json

from fastapi import APIRouter, Query, Request

from app.api.auth import require_settings_api_key

router = APIRouter(prefix="/api")


def parse_redis_candles(raw_list: list[str]) -> list[dict]:
    return [json.loads(c) for c in raw_list]


@router.get("/candles")
async def get_candles(
    request: Request,
    _key: str = require_settings_api_key(),
    pair: str = Query(...),
    timeframe: str = Query(...),
    limit: int = Query(200, ge=1, le=500),
):
    redis = request.app.state.redis
    cache_key = f"candles:{pair}:{timeframe}"
    raw = await redis.lrange(cache_key, -limit, -1)
    return parse_redis_candles(raw)
