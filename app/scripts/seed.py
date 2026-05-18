"""Seed the database with a test manager and a test agent.

Run inside the backend container:
    python -m app.scripts.seed

Idempotent: existing users (matched by email) are left untouched.
"""
import asyncio

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import User, UserRole

SEED_USERS = [
    {
        "email": "manager@b2cagent.test",
        "full_name": "Test Manager",
        "role": UserRole.manager,
        "google_sub": "seed-google-sub-manager",
        "phone": "+15555550100",
        "phone_verified": True,
    },
    {
        "email": "agent@b2cagent.test",
        "full_name": "Test Agent",
        "role": UserRole.agent,
        "google_sub": "seed-google-sub-agent",
        "phone": "+15555550101",
        "phone_verified": True,
    },
]


async def seed() -> None:
    async with SessionLocal() as session:
        for data in SEED_USERS:
            existing = await session.scalar(
                select(User).where(User.email == data["email"])
            )
            if existing:
                print(f"skip   {existing!r}")
                continue
            user = User(**data)
            session.add(user)
            await session.flush()
            print(f"create {user!r}")
        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed())
