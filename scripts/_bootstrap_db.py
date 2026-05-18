"""One-shot bootstrap: create all tables from current models, then stamp alembic.

For local dev only. Run from API/ dir against a fresh empty database:
    DATABASE_URL=... JWT_SECRET=... python -m scripts._bootstrap_db
"""
import asyncio

from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.database import Base
from app import models  # noqa: F401  register models on Base.metadata


async def main() -> None:
    engine = create_async_engine(settings.DATABASE_URL, echo=True, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print("\nTables created.")


if __name__ == "__main__":
    asyncio.run(main())
