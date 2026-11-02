import argparse
import asyncio

from app.config import get_settings
from app.database import async_session_factory
from app.integrations.equipe.client import EquipeClient
from app.services.event_service import EventService


async def import_show(meeting_id: str) -> None:
    settings = get_settings()
    client = EquipeClient(settings.equipe_base_url)
    try:
        async with async_session_factory() as db:
            event, is_new = await EventService(db).import_equipe_meeting(client, meeting_id)
            await db.commit()
            action = "created" if is_new else "updated"
            print(f"{action}: {event.id} {event.name} equipe_id={event.equipe_id}")
    finally:
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Import one Equipe show by meeting id.")
    parser.add_argument("meeting_id", help="Equipe show/meeting id, e.g. 79213")
    args = parser.parse_args()
    asyncio.run(import_show(args.meeting_id))


if __name__ == "__main__":
    main()
