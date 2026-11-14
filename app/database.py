from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

settings = get_settings()

# Run every API session in UTC, whatever the server's default zone is (prod is America/New_York).
# Alembic uses its own engine on purpose: the timestamptz migration needs the server's zone.
_connect_args = (
    {"server_settings": {"timezone": "UTC"}} if settings.database_url.startswith("postgresql+asyncpg") else {}
)
engine = create_async_engine(settings.database_url, echo=settings.database_echo, connect_args=_connect_args)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """One session per request, committed when the endpoint returns.

    Always use `Depends(get_db, scope="function")`: the default scope commits only
    after the response is sent, so a client could not yet use what it just created.
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))


async def create_schema() -> None:
    from app.models import event, order, photographer, user  # noqa: F401
    from app.models.base import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
