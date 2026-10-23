import uuid

import stripe
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.exceptions import ConflictError, ForbiddenError
from app.integrations.clerk.auth import get_current_user, require_role
from app.integrations.stripe.client import get_stripe_client, stripe_error
from app.models.enums import OrderStatus, PaymentTransactionStatus, PaymentTransactionType, UserRole
from app.models.user import User
from app.schemas.order import OrderResponse
from app.services.order_service import OrderService
from app.services.payout_service import PayoutService

router = APIRouter(prefix="/api/v1/orders", tags=["orders"])


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


@router.post("/{order_id}/refund", response_model=OrderResponse)
async def refund(
    order_id: uuid.UUID,
    user: User = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
    stripe_client: stripe.StripeClient = Depends(get_stripe_client),
):
    """Refund the whole order. Its downloads stop working (they need a captured order)."""
    service = OrderService(db)
    order = await service.get_order(order_id)
    if order.status != OrderStatus.CAPTURED:
        raise ConflictError(f"Cannot refund order in {order.status.value} state")
    if not order.stripe_payment_intent_id:
        raise ConflictError("Order has no Stripe payment to refund")

    try:
        stripe_refund = await stripe_client.v1.refunds.create_async(
            {"payment_intent": order.stripe_payment_intent_id},
            {"idempotency_key": f"refund-{order.id}"},
        )
    except stripe.StripeError as exc:
        await service.record_transaction(
            order_id,
            PaymentTransactionType.REFUND,
            PaymentTransactionStatus.FAILED,
            payload={"stripe_payment_intent_id": order.stripe_payment_intent_id, "error": str(exc)},
        )
        raise stripe_error(exc, "refund") from exc

    order = await service.update_order_status(order_id, OrderStatus.REFUNDED)
    # Take the photographers' shares back (or cancel ones not yet sent)
    await PayoutService(db, stripe_client, get_settings()).reverse_order(order)
    await service.record_transaction(
        order_id,
        PaymentTransactionType.REFUND,
        PaymentTransactionStatus.SUCCESS,
        payload={
            "stripe_payment_intent_id": order.stripe_payment_intent_id,
            "stripe_refund_id": stripe_refund.id,
        },
    )
    order = await service.get_order(order_id)
    return OrderResponse.model_validate(order)
