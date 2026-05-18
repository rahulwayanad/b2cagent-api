"""Shared fixtures for auth tests.

Strategy: SQLite-in-memory for the DB, fakeredis for Redis, stub Google OAuth
client, and recording email/SMS senders. Everything is wired via FastAPI's
`dependency_overrides` so the real app code paths are exercised end-to-end.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "test-secret-key-must-be-long-enough")

import pytest
import pytest_asyncio
from fakeredis import aioredis as fakeredis_aio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.redis import get_redis
from app.core.security import create_access_token
from app.main import app
from app.models import User, UserRole
from app.services.google_oauth import GoogleOAuthClient, GoogleUserInfo, get_google_client
from app.services.notifications import get_email_sender, get_sms_sender
from app.services.storage_service import Storage, get_storage


class RecordingEmailSender:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, *, to: str, subject: str, body: str) -> None:
        self.sent.append({"to": to, "subject": subject, "body": body})


class RecordingSMSSender:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, *, to: str, body: str) -> None:
        self.sent.append({"to": to, "body": body})


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def upload(self, *, key: str, data: bytes, content_type: str) -> str:
        self.objects[key] = data
        return f"memory://{key}"

    async def delete(self, *, url: str) -> None:
        prefix = "memory://"
        if url.startswith(prefix):
            self.objects.pop(url[len(prefix):], None)


class StubGoogleClient(GoogleOAuthClient):
    def __init__(self, userinfo: GoogleUserInfo) -> None:
        self._userinfo = userinfo

    async def exchange_code(self, code: str) -> str:
        return "stub-access-token"

    async def fetch_userinfo(self, access_token: str) -> GoogleUserInfo:
        return self._userinfo


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncSession:
    SessionLocal = async_sessionmaker(db_engine, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def fake_redis():
    client = fakeredis_aio.FakeRedis(decode_responses=True)
    yield client
    await client.flushall()
    await client.aclose()


@pytest.fixture
def google_userinfo() -> GoogleUserInfo:
    return GoogleUserInfo(
        sub="google-sub-123",
        email="newuser@example.com",
        name="New User",
    )


@pytest.fixture
def stub_google(google_userinfo) -> StubGoogleClient:
    return StubGoogleClient(google_userinfo)


@pytest.fixture
def email_sender() -> RecordingEmailSender:
    return RecordingEmailSender()


@pytest.fixture
def sms_sender() -> RecordingSMSSender:
    return RecordingSMSSender()


@pytest.fixture
def storage() -> MemoryStorage:
    return MemoryStorage()


@pytest_asyncio.fixture
async def client(db_session, fake_redis, stub_google, email_sender, sms_sender, storage):
    async def _db_override():
        yield db_session

    async def _redis_override():
        yield fake_redis

    app.dependency_overrides[get_db] = _db_override
    app.dependency_overrides[get_redis] = _redis_override
    app.dependency_overrides[get_google_client] = lambda: stub_google
    app.dependency_overrides[get_email_sender] = lambda: email_sender
    app.dependency_overrides[get_sms_sender] = lambda: sms_sender
    app.dependency_overrides[get_storage] = lambda: storage

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def manager_user(db_session) -> User:
    user = User(
        email="manager@test.local",
        full_name="Test Manager",
        google_sub="sub-manager",
        role=UserRole.manager,
        phone_verified=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def other_manager(db_session) -> User:
    user = User(
        email="other-manager@test.local",
        full_name="Other Manager",
        google_sub="sub-other-manager",
        role=UserRole.manager,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def agent_user(db_session) -> User:
    user = User(
        email="agent@test.local",
        full_name="Test Agent",
        google_sub="sub-agent",
        role=UserRole.agent,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def other_agent(db_session) -> User:
    user = User(
        email="other-agent@test.local",
        full_name="Other Agent",
        google_sub="sub-other-agent",
        role=UserRole.agent,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def super_admin_user(db_session) -> User:
    user = User(
        email="root@test.local",
        full_name="Super Admin",
        google_sub="sub-super-admin",
        role=UserRole.super_admin,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def _auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(
        sub=str(user.id), role=user.role.value, email=user.email
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def manager_headers(manager_user) -> dict[str, str]:
    return _auth_headers(manager_user)


@pytest.fixture
def other_manager_headers(other_manager) -> dict[str, str]:
    return _auth_headers(other_manager)


@pytest.fixture
def agent_headers(agent_user) -> dict[str, str]:
    return _auth_headers(agent_user)


@pytest.fixture
def other_agent_headers(other_agent) -> dict[str, str]:
    return _auth_headers(other_agent)


@pytest.fixture
def super_admin_headers(super_admin_user) -> dict[str, str]:
    return _auth_headers(super_admin_user)
