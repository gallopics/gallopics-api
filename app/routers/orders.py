import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.exceptions import ConflictError, ForbiddenError
from app.integrations.clerk.auth import get_current_user, require_role
from app.models.enums import OrderStatus, PaymentTransactionStatus, PaymentTransactionType, UserRole
from app.models.user import User
from app.schemas.order import OrderResponse
from app.services.order_service import OrderService

router = APIRouter(prefix="/api/v1/orders", tags=["orders"])

_VALID_TRANSITIONS = {
    "capture": {OrderStatus.AUTHORIZED},
    "refund": {OrderStatus.CAPTURED},
    "cancel": {OrderStatus.AUTHORIZED},
}


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = OrderService(db)
    order = await service.get_order(order_id)
    if order.user_id != user.id and user.role != UserRole.ADMIN:
        raise ForbiddenError("Not authorized to view this order")
    return OrderResponse.model_validate(order)


@router.post("/{order_id}/capture", response_model=OrderResponse)
async def capture(
    order_id: uuid.UUID,
    user: User = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    service = OrderService(db)
    order = await service.get_order(order_id)
    if order.status not in _VALID_TRANSITIONS["capture"]:
        raise ConflictError(f"Cannot capture order in {order.status} state")
    order = await service.update_order_status(order_id, OrderStatus.CAPTURED)
    await service.record_transaction(
        order_id, PaymentTransactionType.CAPTURE, PaymentTransactionStatus.SUCCESS
    )
    order = await service.get_order(order_id)
    return OrderResponse.model_validate(order)


@router.post("/{order_id}/refund", response_model=OrderResponse)
async def refund(
    order_id: uuid.UUID,
    user: User = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    service = OrderService(db)
    order = await service.get_order(order_id)
    if order.status not in _VALID_TRANSITIONS["refund"]:
        raise ConflictError(f"Cannot refund order in {order.status} state")
    order = await service.update_order_status(order_id, OrderStatus.REFUNDED)
    await service.record_transaction(
        order_id, PaymentTransactionType.REFUND, PaymentTransactionStatus.SUCCESS
    )
    order = await service.get_order(order_id)
    return OrderResponse.model_validate(order)


@router.post("/{order_id}/cancel", response_model=OrderResponse)
async def cancel(
    order_id: uuid.UUID,
    user: User = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    service = OrderService(db)
    order = await service.get_order(order_id)
    if order.status not in _VALID_TRANSITIONS["cancel"]:
        raise ConflictError(f"Cannot cancel order in {order.status} state")
    order = await service.update_order_status(order_id, OrderStatus.CANCELLED)
    await service.record_transaction(
        order_id, PaymentTransactionType.CANCEL, PaymentTransactionStatus.SUCCESS
    )
    order = await service.get_order(order_id)
    return OrderResponse.model_validate(order)
