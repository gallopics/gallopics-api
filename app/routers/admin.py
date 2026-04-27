import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.integrations.clerk.auth import require_role
from app.models.enums import OrderStatus, UserRole
from app.models.order import Order
from app.models.user import User
from app.schemas import PaginatedResponse
from app.schemas.admin import ManualMatchRequest
from app.schemas.event import EventResponse
from app.schemas.order import OrderResponse
from app.services.matching_service import MatchingService

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
