import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError
from app.models.user import User


class UserService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_or_create_by_clerk_id(
        self, clerk_user_id: str, email: str
    ) -> tuple[User, bool]:
        result = await self.db.execute(
            select(User).where(User.clerk_user_id == clerk_user_id)
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing, False

        user = User(clerk_user_id=clerk_user_id, email=email)
        self.db.add(user)
        await self.db.flush()
        return user, True

    async def get_user(self, user_id: uuid.UUID) -> User:
        user = await self.db.get(User, user_id)
        if not user:
            raise NotFoundError("User not found")
        return user

    async def get_user_by_clerk_id(self, clerk_user_id: str) -> User:
        result = await self.db.execute(
            select(User).where(User.clerk_user_id == clerk_user_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            raise NotFoundError("User not found")
        return user
