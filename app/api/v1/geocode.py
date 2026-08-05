"""Server-side proxy in front of Nominatim.

Nominatim's free public tier rate-limits aggressively when many browser
clients hammer it without a proper User-Agent (see usage policy). Routing
through here lets us:

  * send a polite UA that identifies the app
  * throttle and cache in Redis so we don't burn through their quota
  * fall back / swap providers later without touching every frontend page
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from redis.asyncio import Redis

from app.core.redis import get_redis


router = APIRouter(prefix="/geocode", tags=["geocode"])


NOMINATIM_BASE = "https://nominatim.openstreetmap.org"
# Identify the app per Nominatim's usage policy.
USER_AGENT = "b2cagent/1.0 (https://b2cagent.xyz; info@b2cagent.xyz)"
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json",
    "Accept-Language": "en",
    "Referer": "https://b2cagent.xyz",
}
# Cache hits for 12 hours — geocoding results are highly stable.
CACHE_TTL_SEC = 12 * 60 * 60


def _cache_key(kind: str, payload: str) -> str:
    digest = hashlib.sha1(payload.encode()).hexdigest()[:16]
    return f"geocode:{kind}:{digest}"


async def _cached_get(
    redis: Redis, url: str, cache_key: str
) -> Any:
    cached = await redis.get(cache_key)
    if cached is not None:
        return json.loads(cached)
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url, headers=HEADERS)
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Map service timed out. Try again.",
        )
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Map service unreachable: {type(e).__name__}",
        )
    if resp.status_code in (403, 429):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Map service is rate-limiting. Try again in a minute.",
        )
    if resp.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Map service error {resp.status_code}",
        )
    data = resp.json()
    # Cache JSON-serialisable payload only; ignore cache failures.
    try:
        await redis.set(cache_key, json.dumps(data), ex=CACHE_TTL_SEC)
    except Exception:  # noqa: BLE001
        pass
    return data


@router.get("/search")
async def geocode_search(
    q: str = Query(..., min_length=2, max_length=200),
    limit: int = Query(5, ge=1, le=10),
    redis: Redis = Depends(get_redis),
) -> list[dict]:
    """Forward-geocode a free-text place into list of candidates."""
    url = (
        f"{NOMINATIM_BASE}/search"
        f"?format=json&addressdetails=1&accept-language=en&limit={limit}"
        f"&q={httpx.QueryParams({'q': q})['q']}"
    )
    cache_key = _cache_key("search", f"{q.strip().lower()}|{limit}")
    return await _cached_get(redis, url, cache_key)


@router.get("/reverse")
async def geocode_reverse(
    lat: float = Query(...),
    lng: float = Query(...),
    zoom: int = Query(18, ge=3, le=18),
    redis: Redis = Depends(get_redis),
) -> dict:
    """Reverse-geocode (lat, lng) → address breakdown."""
    url = (
        f"{NOMINATIM_BASE}/reverse"
        f"?format=json&addressdetails=1&accept-language=en"
        f"&lat={lat}&lon={lng}&zoom={zoom}"
    )
    cache_key = _cache_key("reverse", f"{lat:.5f},{lng:.5f},{zoom}")
    return await _cached_get(redis, url, cache_key)
