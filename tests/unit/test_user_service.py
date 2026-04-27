import uuid

import pytest

from app.exceptions import NotFoundError
from app.services.user_service import UserService


@pytest.fixture
def service(db_session):
    return UserService(db_session)


async def test_get_or_create_creates_new_user(service):
    user, is_new = await service.get_or_create_by_clerk_id("clerk_abc", "a@b.com")
    assert is_new is True
    assert user.clerk_user_id == "clerk_abc"
    assert user.email == "a@b.com"


async def test_get_or_create_returns_existing(service):
    user1, _ = await service.get_or_create_by_clerk_id("clerk_xyz", "x@y.com")
    user2, is_new = await service.get_or_create_by_clerk_id("clerk_xyz", "x@y.com")
    assert is_new is False
    assert user1.id == user2.id


async def test_get_user_not_found(service):
    with pytest.raises(NotFoundError):
        await service.get_user(uuid.uuid4())
