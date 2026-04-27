import uuid
from unittest.mock import AsyncMock, patch

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.enums import UserRole
from app.models.user import User

test_engine = create_async_engine("sqlite+aiosqlite://", echo=False)
TestSessionFactory = async_sessionmaker(test_engine, expire_on_commit=False)


@pytest.fixture(scope="session", autouse=True)
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
def rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key


@pytest.fixture(scope="session")
def rsa_public_key(rsa_keypair):
    return rsa_keypair.public_key()


@pytest.fixture
async def db_session():
    from app.models.base import Base

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestSessionFactory() as session:
        yield session
        await session.rollback()

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
def make_jwt(rsa_keypair):
    def _make(claims: dict) -> str:
        return pyjwt.encode(claims, rsa_keypair, algorithm="RS256")
    return _make


@pytest.fixture
async def async_client(db_session, rsa_keypair, rsa_public_key):
    import httpx

    from app.database import get_db
    from app.integrations.clerk.auth import ClerkAuth, get_current_user
    from app.main import app

    async def _override_get_db():
        yield db_session

    # Patch ClerkAuth to use test RSA key
    original_validate = ClerkAuth.validate_token

    def _mock_validate(self, token: str) -> dict:
        return pyjwt.decode(token, rsa_public_key, algorithms=["RS256"], options={"verify_aud": False})

    app.dependency_overrides[get_db] = _override_get_db

    with patch.object(ClerkAuth, "validate_token", _mock_validate):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield client

    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers(make_jwt):
    token = make_jwt({"sub": "clerk_user_test", "email": "test@example.com"})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def admin_user(db_session):
    user = User(clerk_user_id="clerk_admin_test", email="admin@example.com", role=UserRole.ADMIN)
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
def admin_auth_headers(make_jwt, admin_user):
    token = make_jwt({"sub": "clerk_admin_test", "email": "admin@example.com"})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def photographer_user(db_session):
    user = User(clerk_user_id="clerk_photographer_test", email="photo@example.com", role=UserRole.PHOTOGRAPHER)
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
def photographer_auth_headers(make_jwt, photographer_user):
    token = make_jwt({"sub": "clerk_photographer_test", "email": "photo@example.com"})
    return {"Authorization": f"Bearer {token}"}
