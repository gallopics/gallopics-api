from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.integrations.clerk.auth import require_role
from app.models.enums import OrderStatus, UserRole
from app.models.event import Event
from app.models.order import Order
from app.models.photographer import Photo, PhotoPurchase
from app.models.user import User
from app.schemas.sales import SaleItem, SalesResponse, SalesTotals
from app.services.payout_service import FAILED, OWED, TRANSFERRED, split_amount
from app.services.photographer_service import PhotographerService
from app.services.stripe_connect_service import PAYOUT_DAY_OF_MONTH

router = APIRouter(prefix="/api/v1/photographer/sales", tags=["photographer-sales"])


@router.get("", response_model=SalesResponse)
async def list_my_sales(
    user: User = Depends(require_role(UserRole.PHOTOGRAPHER)),
    db: AsyncSession = Depends(get_db),
):
    """Every paid (or later refunded) sale of this photographer's photos, newest first."""
    settings = get_settings()
    photographer = await PhotographerService(db).get_photographer_for_user(user.id)
    result = await db.execute(
        select(PhotoPurchase, Photo, Event, Order)
        .join(Photo, Photo.id == PhotoPurchase.photo_id)
        .join(Event, Event.id == Photo.event_id)
        .join(Order, Order.id == PhotoPurchase.order_id)
        .where(
            Photo.photographer_id == photographer.id,
            Order.status.in_([OrderStatus.CAPTURED, OrderStatus.REFUNDED]),
        )
        .order_by(PhotoPurchase.created_at.desc())
    )

    items = []
    for purchase, photo, event, order in result.all():
        share = purchase.photographer_amount
        if share is None:  # sold before payouts existed: show the share at today's rate
            share, _ = split_amount(purchase.amount, settings.platform_commission_percent)
        items.append(
            SaleItem(
                id=purchase.id,
                photo_id=photo.id,
                event_id=event.id,
                event_name=event.name,
                class_name=photo.class_name,
                quality=purchase.quality,
                amount=purchase.amount,
                photographer_amount=share,
                currency=purchase.currency,
                sold_at=purchase.created_at,
                refunded=order.status == OrderStatus.REFUNDED,
                payout_status=purchase.payout_status,
            )
        )

    active = [item for item in items if not item.refunded]
    totals = SalesTotals(
        count=len(active),
        amount=sum(item.amount for item in active),
        photographer_amount=sum(item.photographer_amount for item in active),
        transferred=sum(item.photographer_amount for item in active if item.payout_status == TRANSFERRED),
        owed=sum(item.photographer_amount for item in active if item.payout_status in (OWED, FAILED)),
    )
    return SalesResponse(
        items=items,
        totals=totals,
        commission_percent=settings.platform_commission_percent,
        payout_day_of_month=PAYOUT_DAY_OF_MONTH,
    )
