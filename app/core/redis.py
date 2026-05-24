from collections.abc import AsyncIterator

from redis.asyncio import Redis, from_url

from app.core.config import settings


async def get_redis() -> AsyncIterator[Redis]:
    # Create a fresh client per request — avoids "Future attached to a
    # different loop" errors under Passenger where each request runs in
    # its own asyncio.run() / event loop.
    client = from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()
