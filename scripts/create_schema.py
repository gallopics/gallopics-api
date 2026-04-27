import asyncio

from app.database import create_schema


async def main() -> None:
    await create_schema()


if __name__ == "__main__":
    asyncio.run(main())
