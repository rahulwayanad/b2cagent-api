from collections.abc import AsyncIterator

from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

# NullPool is required under Passenger/WSGI where each request runs in a
# fresh asyncio.run() call (new event loop). Connection pooling caches
# aiomysql sockets that are bound to the previous loop, causing:
#   RuntimeError: Task got Future attached to a different loop
# With NullPool every request opens and closes its own connection.
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    poolclass=NullPool,
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
