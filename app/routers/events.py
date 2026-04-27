import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.enums import EventStatus
from app.schemas import PaginatedResponse
from app.schemas.event import EventFilters, EventResponse, EventResultResponse
from app.services.event_service import EventService

router = APIRouter(prefix="/api/v1/events", tags=["events"])


@router.get("", response_model=PaginatedResponse[EventResponse])
async def list_events(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    discipline: Optional[str] = None,
    horse_type: Optional[str] = None,
    district: Optional[str] = None,
    organizer: Optional[str] = None,
    status: Optional[EventStatus] = None,
    is_sustainable: Optional[bool] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    filters = EventFilters(
        date_from=date_from,
        date_to=date_to,
        discipline=discipline,
        horse_type=horse_type,
        district=district,
        organizer=organizer,
        status=status,
        is_sustainable=is_sustainable,
        search=search,
    )
    service = EventService(db)
    items, total = await service.list_events(filters, page, page_size)
    return PaginatedResponse(
        items=[EventResponse.model_validate(e) for e in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(event_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    service = EventService(db)
    event = await service.get_event(event_id)
    return EventResponse.model_validate(event)


@router.get("/{event_id}/results", response_model=list[EventResultResponse])
async def get_event_results(event_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    service = EventService(db)
    results = await service.get_event_results(event_id)
    return [EventResultResponse.model_validate(r) for r in results]
