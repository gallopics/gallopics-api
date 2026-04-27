from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.integrations.equipe.client import EquipeClient
from app.integrations.equipe.normalizer import normalize_equipe_meeting, normalize_equipe_results
from app.integrations.tdb.client import TDBClient
from app.schemas.event import EventResponse
from app.services.event_service import EventService
from app.services.matching_service import MatchingService

router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])


@router.post("/tdb/sync")
async def trigger_tdb_sync(db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    tdb_client = TDBClient(settings.tdb_base_url)
    try:
        service = EventService(db)
        result = await service.sync_from_tdb(tdb_client)
        return result
    finally:
        await tdb_client.close()


@router.post("/equipe/sync")
async def trigger_equipe_sync(db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    equipe_client = EquipeClient(settings.equipe_base_url)
    try:
        raw_meetings = await equipe_client.get_meetings()
        normalized = [normalize_equipe_meeting(m) for m in raw_meetings]

        matching_service = MatchingService(db)
        match_result = await matching_service.run_matching_batch(normalized)

        # Import results for matched events
        event_service = EventService(db)
        results_imported = 0
        for raw_meeting, norm in zip(raw_meetings, normalized):
            equipe_id = norm.get("equipe_id")
            if not equipe_id:
                continue
            # Check if this meeting was matched by looking up the event
            from sqlalchemy import select
            from app.models.event import Event
            result = await db.execute(select(Event).where(Event.equipe_id == equipe_id))
            event = result.scalar_one_or_none()
            if event:
                raw_results = await equipe_client.get_meeting_results(equipe_id)
                norm_results = normalize_equipe_results(raw_results)
                await event_service.upsert_event_results(event.id, norm_results)
                results_imported += len(norm_results)

        return {**match_result, "results_imported": results_imported}
    finally:
        await equipe_client.close()


@router.post("/events/rematch")
async def trigger_rematch(db: AsyncSession = Depends(get_db)):
    matching_service = MatchingService(db)
    unmatched = await matching_service.get_unmatched_events()
    # Re-run is a no-op without Equipe data; this endpoint is useful after new events are synced
    return {"unmatched_count": len(unmatched)}


@router.get("/events/unmatched", response_model=list[EventResponse])
async def get_unmatched_events(db: AsyncSession = Depends(get_db)):
    matching_service = MatchingService(db)
    events = await matching_service.get_unmatched_events()
    return [EventResponse.model_validate(e) for e in events]
