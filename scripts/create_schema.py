import asyncio

from app.database import engine
from app.models import event, order, photographer, user  # noqa: F401
from app.models.base import Base


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


if __name__ == "__main__":
    asyncio.run(main())
