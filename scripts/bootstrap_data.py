import asyncio

from app.config import get_settings
from app.database import async_session_factory
from app.integrations.equipe.client import EquipeClient
from app.services.event_service import EventService


async def sync_equipe() -> dict:
    settings = get_settings()
    if not settings.equipe_base_url:
        return {"skipped": True, "reason": "EQUIPE_BASE_URL is not set"}

    client = EquipeClient(settings.equipe_base_url)
    try:
        async with async_session_factory() as db:
            result = await EventService(db).sync_from_equipe(client, country="swe")
            await db.commit()
            return result
    finally:
        await client.close()


async def main() -> None:
    print("Syncing Equipe meetings...")
    print(await sync_equipe())


if __name__ == "__main__":
    asyncio.run(main())
