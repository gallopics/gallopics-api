import uuid
from typing import Any, Optional

import stripe
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.exceptions import BadRequestError, NotFoundError
from app.integrations.stripe.client import stripe_error
from app.models.enums import OrderStatus, PaymentTransactionStatus, PaymentTransactionType, PhotoStatus
from app.models.order import Order
from app.models.photographer import Photo
from app.models.user import User
from app.schemas.checkout import CheckoutItem
from app.services.order_service import OrderService
from app.services.payout_service import PayoutService
from app.services.pricing import CURRENCY, get_quality_tier
from app.services.transactional_email_service import TransactionalEmailService

logger = structlog.get_logger()


def photo_urls(base_url: str, photo_id: str, order_id: uuid.UUID) -> dict[str, str]:
    base_url = base_url.rstrip("/")
    return {
        "thumbnail_url": f"{base_url}/api/v1/photographer/photos/{photo_id}/thumbnail",
        "download_url": f"{base_url}/api/v1/photos/{photo_id}/download?order_id={order_id}&inline=true",
    }


class CheckoutService:
    def __init__(
        self,
        db: AsyncSession,
        stripe_client: Optional[stripe.StripeClient],
        settings: Settings,
        public_base_url: str,
    ):
        self.db = db
        self.stripe = stripe_client
        self.settings = settings
        # Base for photo links in receipts (API_PUBLIC_BASE_URL, else the request's own URL)
        self.public_base_url = settings.api_public_base_url or public_base_url
        self.orders = OrderService(db)

    async def create_session(
        self,
        user: User,
        items: list[CheckoutItem],
        customer_email: str,
        cancel_path: Optional[str] = None,
    ) -> tuple[Order, stripe.checkout.Session]:
        line_items = await self._price_items(items)
        order = await self.orders.create_order(
            user_id=user.id,
            amount=sum(item["total_amount"] for item in line_items),
            currency=CURRENCY,
        )
        order.customer_email = customer_email
        order.line_items = line_items
        await self.db.flush()

        frontend_url = self.settings.frontend_base_url.rstrip("/")
        params: dict[str, Any] = {
            "mode": "payment",
            "line_items": [
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": CURRENCY.lower(),
                        "unit_amount": item["total_amount"],
                        "product_data": {
                            "name": item["name"],
                            "metadata": {"photo_id": item["photo_id"], "quality": item["quality"]},
                        },
                    },
                }
                for item in line_items
            ],
            "customer_email": customer_email,
            "client_reference_id": str(order.id),
            "metadata": {"order_id": str(order.id)},
            "payment_intent_data": {"metadata": {"order_id": str(order.id)}},
            # Stripe fills in {CHECKOUT_SESSION_ID} itself
            "success_url": f"{frontend_url}/cart/success?session_id={{CHECKOUT_SESSION_ID}}",
            "cancel_url": f"{frontend_url}{cancel_path or '/cart'}",
        }
        try:
            session = await self._stripe().v1.checkout.sessions.create_async(
                params,
                {"idempotency_key": f"checkout-session-{order.id}"},
            )
        except stripe.StripeError as exc:
            raise stripe_error(exc, "checkout session creation") from exc

        order.stripe_checkout_session_id = session.id
        await self.orders.record_transaction(
            order.id,
            PaymentTransactionType.AUTHORIZATION,
            PaymentTransactionStatus.PENDING,
            payload={"stripe_checkout_session_id": session.id},
        )
        await self.db.flush()
        return order, session

    async def get_order_for_session(self, session_id: str) -> Order:
        """The order behind a Checkout Session; checks Stripe if the webhook hasn't arrived yet."""
        order = await self._find_order(session_id)
        if order.status == OrderStatus.PENDING:
            try:
                session = await self._stripe().v1.checkout.sessions.retrieve_async(session_id)
            except stripe.StripeError as exc:
                raise stripe_error(exc, "checkout session lookup") from exc
            order = await self.fulfill(session)
        return order

    async def fulfill(self, session: stripe.checkout.Session) -> Order:
        """Mark a paid session's order captured. Safe to call twice (webhook + success page)."""
        order = await self._find_order(session.id, lock=True)
        if order.status != OrderStatus.PENDING or session.payment_status != "paid":
            return order

        amount_paid = session.amount_total
        currency_paid = (session.currency or "").upper()
        if amount_paid != order.amount or currency_paid != order.currency:
            # Never expected: the session was created from this order's own total
            logger.error(
                "stripe_amount_mismatch",
                order_id=str(order.id),
                expected=order.amount,
                paid=amount_paid,
                currency=currency_paid,
            )
            await self.orders.record_transaction(
                order.id,
                PaymentTransactionType.CAPTURE,
                PaymentTransactionStatus.FAILED,
                payload={"stripe_checkout_session_id": session.id, "error": "amount_mismatch"},
            )
            return order

        payment_intent = session.payment_intent
        order.stripe_payment_intent_id = (
            payment_intent if isinstance(payment_intent, str) else getattr(payment_intent, "id", None)
        )
        order.status = OrderStatus.CAPTURED
        line_items = order.line_items or []
        purchases = await self.orders.create_photo_purchases(order, line_items)

        # Each photographer's share: recorded now, transferred if they're connected
        payouts = PayoutService(self.db, self.stripe, self.settings)
        photographer_by_photo = {item["photo_id"]: item.get("photographer_id") for item in line_items}
        for purchase in purchases:
            payouts.apply_split(purchase, photographer_by_photo.get(str(purchase.photo_id)))
        await self.db.flush()
        try:
            await payouts.settle_order(order)
        except Exception as exc:  # the sale stands; owed shares are retried later
            logger.error("payout_settle_failed", order_id=str(order.id), error=str(exc))

        receipt_items = [
            {**item, **photo_urls(self.public_base_url, item["photo_id"], order.id)} for item in line_items
        ]
        try:
            receipt_email = await TransactionalEmailService(self.settings).send_purchase_receipt(
                recipient_email=order.customer_email,
                order_id=str(order.id),
                amount=order.amount,
                currency=order.currency,
                line_items=receipt_items,
            )
        except Exception as exc:  # the payment stands even if the email fails
            receipt_email = {"status": "failed", "error": str(exc)}

        await self.orders.record_transaction(
            order.id,
            PaymentTransactionType.CAPTURE,
            PaymentTransactionStatus.SUCCESS,
            payload={
                "stripe_checkout_session_id": session.id,
                "stripe_payment_intent_id": order.stripe_payment_intent_id,
                "purchase_receipt_email": receipt_email,
            },
        )
        await self.db.flush()
        return order

    async def cancel_unpaid(self, session: stripe.checkout.Session) -> Optional[Order]:
        """An expired or failed session: its order will never be paid."""
        try:
            order = await self._find_order(session.id, lock=True)
        except NotFoundError:
            return None
        if order.status == OrderStatus.PENDING:
            order.status = OrderStatus.CANCELLED
            await self.db.flush()
        return order

    async def _price_items(self, items: list[CheckoutItem]) -> list[dict[str, Any]]:
        # One line per photo + quality, even if the cart repeats it
        unique_items = list({(item.photo_id, item.quality): item for item in items}.values())
        photo_ids = {item.photo_id for item in unique_items}
        result = await self.db.execute(select(Photo).where(Photo.id.in_(photo_ids)))
        photos = {photo.id: photo for photo in result.scalars()}

        line_items = []
        for item in unique_items:
            photo = photos.get(item.photo_id)
            if not photo or photo.status != PhotoStatus.READY or not photo.storage_key_original:
                raise BadRequestError(f"Photo #{str(item.photo_id)[:8].upper()} is no longer available for purchase")
            tier = get_quality_tier(item.quality)
            name = f"Photo #{str(photo.id)[:8].upper()} – {tier.label}"
            line_items.append(
                {
                    "photo_id": str(photo.id),
                    "photographer_id": str(photo.photographer_id),
                    "quality": tier.id,
                    "name": name,
                    "reference": str(photo.id),
                    "quantity": 1,
                    "unit_price": tier.amount,
                    "total_amount": tier.amount,
                }
            )
        return line_items

    async def _find_order(self, session_id: str, lock: bool = False) -> Order:
        query = (
            select(Order)
            .where(Order.stripe_checkout_session_id == session_id)
            .options(selectinload(Order.transactions))
            .execution_options(populate_existing=True)
        )
        if lock:
            query = query.with_for_update()
        order = (await self.db.execute(query)).scalar_one_or_none()
        if not order:
            raise NotFoundError("Order not found for this checkout session")
        return order

    def _stripe(self) -> stripe.StripeClient:
        if self.stripe is None:
            raise BadRequestError("Stripe is not configured")
        return self.stripe
