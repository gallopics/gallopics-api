import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.database import get_db
from app.exceptions import NotFoundError
from app.integrations.clerk.auth import require_role
from app.integrations.equipe.client import EquipeClient
from app.models.enums import OrderStatus, PhotographerStatus, UserRole
from app.models.order import Order
from app.models.photographer import Photo, Photographer
from app.models.user import User
from app.schemas import PaginatedResponse
from app.schemas.admin import AdminPhotographerResponse, ManualMatchRequest, UpdatePhotographerStatusRequest
from app.schemas.event import EventResponse
from app.schemas.order import OrderResponse
from app.services.event_service import EventService
from app.services.matching_service import MatchingService
from app.services.stripe_connect_service import connect_status

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin"],
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)


@router.get("/orders", response_model=PaginatedResponse[OrderResponse])
async def list_all_orders(
    status: Optional[OrderStatus] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    query = select(Order)
    if status:
        query = query.where(Order.status == status)

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar_one()

    query = query.order_by(Order.created_at.desc())
    query = query.options(selectinload(Order.transactions))
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = list(result.scalars().all())

    return PaginatedResponse(
        items=[OrderResponse.model_validate(o) for o in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/events/{event_id}/match", response_model=EventResponse)
async def manual_match(
    event_id: uuid.UUID,
    body: ManualMatchRequest,
    db: AsyncSession = Depends(get_db),
):
    service = MatchingService(db)
    event = await service.manual_match(event_id, body.equipe_id)
    return EventResponse.model_validate(event)


@router.post("/events/{event_id}/unmatch", response_model=EventResponse)
async def unmatch(
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    service = MatchingService(db)
    event = await service.unmatch(event_id)
    return EventResponse.model_validate(event)


@router.post("/equipe/shows/{meeting_id}/import", response_model=EventResponse)
async def import_equipe_show(
    meeting_id: str,
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()
    equipe_client = EquipeClient(settings.equipe_base_url)
    try:
        service = EventService(db)
        event, _ = await service.import_equipe_meeting(equipe_client, meeting_id)
        return EventResponse.model_validate(event)
    finally:
        await equipe_client.close()


def _admin_photographer(photographer: Photographer, email: str, photo_count: int) -> AdminPhotographerResponse:
    return AdminPhotographerResponse(
        id=photographer.id,
        user_id=photographer.user_id,
        display_name=photographer.display_name,
        slug=photographer.slug,
        email=email or "",
        city=photographer.city,
        country=photographer.country,
        avatar_url=photographer.avatar_url,
        status=photographer.status.value,
        stripe_status=connect_status(photographer),
        photo_count=photo_count,
        created_at=photographer.created_at,
    )


@router.get("/photographers", response_model=list[AdminPhotographerResponse])
async def list_photographers(
    status: Optional[PhotographerStatus] = None,
    db: AsyncSession = Depends(get_db),
):
    """All photographers, newest first (filter with ?status=pending to review sign-ups)."""
    photo_counts = (
        select(Photo.photographer_id, func.count(Photo.id).label("photo_count"))
        .group_by(Photo.photographer_id)
        .subquery()
    )
    query = (
        select(Photographer, User.email, func.coalesce(photo_counts.c.photo_count, 0))
        .join(User, User.id == Photographer.user_id)
        .outerjoin(photo_counts, photo_counts.c.photographer_id == Photographer.id)
        .order_by(Photographer.created_at.desc())
    )
    if status:
        query = query.where(Photographer.status == status)
    result = await db.execute(query)
    return [_admin_photographer(photographer, email, count) for photographer, email, count in result.all()]


@router.patch("/photographers/{photographer_id}", response_model=AdminPhotographerResponse)
async def update_photographer_status(
    photographer_id: uuid.UUID,
    body: UpdatePhotographerStatusRequest,
    db: AsyncSession = Depends(get_db),
):
    """Approve or reject (status "suspended") a photographer, or set them back to pending."""
    photographer = await db.get(Photographer, photographer_id)
    if not photographer:
        raise NotFoundError("Photographer not found")
    photographer.status = body.status
    await db.flush()

    user = await db.get(User, photographer.user_id)
    photo_count = (
        await db.execute(select(func.count(Photo.id)).where(Photo.photographer_id == photographer.id))
    ).scalar_one()
    return _admin_photographer(photographer, user.email if user else "", photo_count)
