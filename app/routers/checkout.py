import uuid
from typing import Optional

import stripe
import structlog
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.exceptions import BadRequestError, NotFoundError
from app.integrations.clerk.auth import get_clerk_auth
from app.integrations.stripe.client import get_stripe_client
from app.models.enums import OrderStatus
from app.models.order import Order
from app.models.user import User
from app.schemas.checkout import (
    CheckoutOrderItem,
    CheckoutOrderResponse,
    CheckoutSessionResponse,
    CreateCheckoutSessionRequest,
)
from app.services.checkout_service import CheckoutService, photo_urls

router = APIRouter(prefix="/api/v1/checkout", tags=["checkout"])
logger = structlog.get_logger()

# Checkout Session events that settle an order
_PAID_EVENTS = {"checkout.session.completed", "checkout.session.async_payment_succeeded"}
_UNPAID_EVENTS = {"checkout.session.expired", "checkout.session.async_payment_failed"}


async def _get_or_create_user(
    auth: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> User:
    if auth and auth.startswith("Bearer "):
        try:
            claims = get_clerk_auth().validate_token(auth[7:])
            from app.services.user_service import UserService

            user_service = UserService(db)
            user, _ = await user_service.get_or_create_by_clerk_id(
                clerk_user_id=claims["sub"],
                email=claims.get("email", ""),
            )
            return user
        except Exception:
            pass

    guest_email = "guest+checkout@gallopics.local"
    result = await db.execute(select(User).where(User.email == guest_email))
    guest = result.scalar_one_or_none()
    if not guest:
        guest = User(
            clerk_user_id=f"guest_{uuid.uuid4()}",
            email=guest_email,
        )
        db.add(guest)
        await db.flush()
        await db.refresh(guest)
    return guest


def _checkout_service(request: Request, db: AsyncSession, stripe_client: Optional[stripe.StripeClient]):
    return CheckoutService(db, stripe_client, get_settings(), public_base_url=str(request.base_url))


def _order_response(order: Order, service: CheckoutService) -> CheckoutOrderResponse:
    items = [
        CheckoutOrderItem(
            photo_id=item["photo_id"],
            quality=item["quality"],
            name=item["name"],
            amount=item["total_amount"],
            thumbnail_url=photo_urls(service.public_base_url, item["photo_id"], order.id)["thumbnail_url"],
        )
        for item in order.line_items or []
    ]
    return CheckoutOrderResponse(
        order_id=order.id,
        status=order.status,
        paid=order.status == OrderStatus.CAPTURED,
        customer_email=order.customer_email,
        amount=order.amount,
        currency=order.currency,
        items=items,
    )


@router.post("/sessions", response_model=CheckoutSessionResponse)
async def create_session(
    body: CreateCheckoutSessionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    stripe_client: stripe.StripeClient = Depends(get_stripe_client),
):
    user = await _get_or_create_user(auth=request.headers.get("authorization"), db=db)
    service = _checkout_service(request, db, stripe_client)
    order, session = await service.create_session(user, body.items, body.customer_email, body.cancel_path)
    return CheckoutSessionResponse(order_id=order.id, session_id=session.id, checkout_url=session.url)


@router.get("/sessions/{session_id}", response_model=CheckoutOrderResponse)
async def get_session_order(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    stripe_client: stripe.StripeClient = Depends(get_stripe_client),
):
    """For the success page. The session id is only known to the buyer who paid."""
    service = _checkout_service(request, db, stripe_client)
    order = await service.get_order_for_session(session_id)
    return _order_response(order, service)


@router.post("/webhook/stripe")
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    stripe_client: stripe.StripeClient = Depends(get_stripe_client),
):
    settings = get_settings()
    if not settings.stripe_webhook_secret:
        raise BadRequestError("Stripe webhook secret is not configured")

    payload = await request.body()
    try:
        event = stripe_client.construct_event(
            payload,
            request.headers.get("stripe-signature"),
            settings.stripe_webhook_secret,
        )
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise BadRequestError("Invalid Stripe webhook signature") from exc

    service = _checkout_service(request, db, stripe_client)
    session = event.data.object
    try:
        if event.type in _PAID_EVENTS:
            await service.fulfill(session)
        elif event.type in _UNPAID_EVENTS:
            await service.cancel_unpaid(session)
        else:
            logger.info("stripe_webhook_ignored", event_type=event.type)
    except NotFoundError:
        # Not one of our sessions (e.g. created in the dashboard): nothing to do, don't make Stripe retry
        logger.warning("stripe_webhook_unknown_session", event_type=event.type, session_id=session.id)

    return {"received": True}
