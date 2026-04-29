from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.integrations.equipe.client import EquipeClient
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
        event_service = EventService(db)
        return await event_service.sync_from_equipe(equipe_client, country="swe")
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
