from collections.abc import AsyncIterator

from redis.asyncio import Redis, from_url

from app.core.config import settings

_client: Redis | None = None


def get_redis_client() -> Redis:
    global _client
    if _client is None:
        _client = from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
    return _client


async def get_redis() -> AsyncIterator[Redis]:
    yield get_redis_client()
