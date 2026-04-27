import asyncio

from sqlalchemy import select

from app.config import get_settings
from app.database import async_session_factory
from app.integrations.equipe.client import EquipeClient
from app.integrations.equipe.normalizer import normalize_equipe_meeting, normalize_equipe_results
from app.integrations.tdb.client import TDBClient
from app.models.event import Event
from app.services.event_service import EventService
from app.services.matching_service import MatchingService


async def sync_tdb() -> dict:
    settings = get_settings()
    if not settings.tdb_base_url:
        return {"skipped": True, "reason": "TDB_BASE_URL is not set"}

    client = TDBClient(settings.tdb_base_url)
    try:
        async with async_session_factory() as db:
            result = await EventService(db).sync_from_tdb(client)
            await db.commit()
            return result
    finally:
        await client.close()


async def sync_equipe() -> dict:
    settings = get_settings()
    if not settings.equipe_base_url:
        return {"skipped": True, "reason": "EQUIPE_BASE_URL is not set"}

    client = EquipeClient(settings.equipe_base_url)
    try:
        async with async_session_factory() as db:
            raw_meetings = await client.get_meetings()
            normalized = [normalize_equipe_meeting(meeting) for meeting in raw_meetings]

            match_result = await MatchingService(db).run_matching_batch(normalized)
            event_service = EventService(db)
            results_imported = 0

            for raw_meeting, normalized_meeting in zip(raw_meetings, normalized):
                equipe_id = normalized_meeting.get("equipe_id")
                if not equipe_id:
                    continue

                result = await db.execute(select(Event).where(Event.equipe_id == equipe_id))
                event = result.scalar_one_or_none()
                if not event:
                    continue

                raw_results = await client.get_meeting_results(equipe_id)
                normalized_results = normalize_equipe_results(raw_results)
                await event_service.upsert_event_results(event.id, normalized_results)
                results_imported += len(normalized_results)

            await db.commit()
            return {**match_result, "results_imported": results_imported}
    finally:
        await client.close()


async def main() -> None:
    print("Syncing TDB events...")
    print(await sync_tdb())

    print("Syncing Equipe meetings and results...")
    print(await sync_equipe())


if __name__ == "__main__":
    asyncio.run(main())
