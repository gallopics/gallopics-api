"""Photographers' share of each sale, sent to their Stripe account as a transfer.

"Separate charges and transfers": the buyer pays Gallopics; after the payment each
photographer gets one transfer per order (their photos' share minus the commission).
Transfers are tied to the buyer's charge (`source_transaction`), so they work before the
funds are available. Stripe pays the balance out to the photographer's bank on the 15th.

Purchase payout_status: owed (waiting for a connected account) → transferred
(→ reversed when the order is refunded) | cancelled (refunded before transfer) |
failed (Stripe refused; retried on the next settle).
"""

import uuid
from collections import defaultdict
from typing import Optional

import stripe
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.enums import OrderStatus
from app.models.order import Order
from app.models.photographer import Photographer, PhotoPurchase
from app.services.stripe_connect_service import connect_status

logger = structlog.get_logger()

OWED = "owed"
TRANSFERRED = "transferred"
REVERSED = "reversed"
CANCELLED = "cancelled"
FAILED = "failed"
_TO_SETTLE = (OWED, FAILED)


def split_amount(amount: int, commission_percent: int) -> tuple[int, int]:
    """(photographer's share, platform fee) of an amount in öre; the share is rounded down."""
    photographer_amount = amount * (100 - commission_percent) // 100
    return photographer_amount, amount - photographer_amount


class PayoutService:
    def __init__(self, db: AsyncSession, stripe_client: Optional[stripe.StripeClient], settings: Settings):
        self.db = db
        self.stripe = stripe_client
        self.settings = settings

    def apply_split(self, purchase: PhotoPurchase, photographer_id: Optional[str]) -> None:
        """Record the photographer's share on a new purchase (owed until transferred)."""
        if not photographer_id:
            return
        purchase.photographer_id = uuid.UUID(str(photographer_id))
        purchase.photographer_amount, purchase.platform_fee = split_amount(
            purchase.amount, self.settings.platform_commission_percent
        )
        purchase.payout_status = OWED

    async def settle_order(self, order: Order) -> None:
        """Transfer the shares of a paid order to every connected photographer in it."""
        purchases = await self._purchases(PhotoPurchase.order_id == order.id)
        await self._settle(order, purchases)

    async def settle_photographer(self, photographer: Photographer) -> None:
        """A photographer just connected: send everything they're owed, order by order."""
        if connect_status(photographer) != "active":
            return
        purchases = await self._purchases(PhotoPurchase.photographer_id == photographer.id)
        by_order: dict[uuid.UUID, list[PhotoPurchase]] = defaultdict(list)
        for purchase in purchases:
            by_order[purchase.order_id].append(purchase)
        for order_id, order_purchases in by_order.items():
            order = await self.db.get(Order, order_id)
            if order and order.status == OrderStatus.CAPTURED:
                await self._settle(order, order_purchases)

    async def reverse_order(self, order: Order) -> None:
        """The order was refunded: take transferred shares back, cancel owed ones."""
        result = await self.db.execute(select(PhotoPurchase).where(PhotoPurchase.order_id == order.id))
        purchases = list(result.scalars())
        by_transfer: dict[str, list[PhotoPurchase]] = defaultdict(list)
        for purchase in purchases:
            if purchase.payout_status in _TO_SETTLE:
                purchase.payout_status = CANCELLED
            elif purchase.payout_status == TRANSFERRED and purchase.stripe_transfer_id:
                by_transfer[purchase.stripe_transfer_id].append(purchase)

        for transfer_id, transferred in by_transfer.items():
            try:
                await self._stripe().v1.transfers.reversals.create_async(
                    transfer_id, options={"idempotency_key": f"reversal-{transfer_id}"}
                )
            except stripe.StripeError as exc:
                # The refund stands; this needs a manual reversal in the dashboard
                logger.error("stripe_transfer_reversal_failed", order_id=str(order.id), transfer_id=transfer_id,
                             error=str(exc))
                continue
            for purchase in transferred:
                purchase.payout_status = REVERSED
        await self.db.flush()

    async def _settle(self, order: Order, purchases: list[PhotoPurchase]) -> None:
        by_photographer: dict[uuid.UUID, list[PhotoPurchase]] = defaultdict(list)
        for purchase in purchases:
            if purchase.payout_status in _TO_SETTLE and purchase.photographer_id:
                by_photographer[purchase.photographer_id].append(purchase)
        if not by_photographer:
            return

        for photographer_id, owed in by_photographer.items():
            photographer = await self.db.get(Photographer, photographer_id)
            if not photographer or connect_status(photographer) != "active":
                continue  # stays owed until they connect
            await self._transfer(order, photographer, owed)
        await self.db.flush()

    async def _transfer(self, order: Order, photographer: Photographer, purchases: list[PhotoPurchase]) -> None:
        amount = sum(purchase.photographer_amount or 0 for purchase in purchases)
        if amount <= 0:
            return
        try:
            charge_id = await self._charge_id(order)
            transfer = await self._stripe().v1.transfers.create_async(
                {
                    "amount": amount,
                    "currency": order.currency.lower(),
                    "destination": photographer.stripe_account_id,
                    "source_transaction": charge_id,
                    "transfer_group": f"order_{order.id}",
                    "description": f"Gallopics sales, order {order.id}",
                    "metadata": {"order_id": str(order.id), "photographer_id": str(photographer.id)},
                },
                {"idempotency_key": f"transfer-{order.id}-{photographer.id}"},
            )
        except stripe.StripeError as exc:
            logger.error("stripe_transfer_failed", order_id=str(order.id), photographer_id=str(photographer.id),
                         error=str(exc))
            for purchase in purchases:
                purchase.payout_status = FAILED
            return

        for purchase in purchases:
            purchase.payout_status = TRANSFERRED
            purchase.stripe_transfer_id = transfer.id

    async def _charge_id(self, order: Order) -> str:
        if not order.stripe_charge_id:
            payment_intent = await self._stripe().v1.payment_intents.retrieve_async(order.stripe_payment_intent_id)
            charge = payment_intent.latest_charge
            order.stripe_charge_id = charge if isinstance(charge, str) else charge.id
        return order.stripe_charge_id

    async def _purchases(self, condition) -> list[PhotoPurchase]:
        result = await self.db.execute(
            select(PhotoPurchase).where(condition, PhotoPurchase.payout_status.in_(_TO_SETTLE))
        )
        return list(result.scalars())

    def _stripe(self) -> stripe.StripeClient:
        if self.stripe is None:
            raise RuntimeError("Stripe is not configured")
        return self.stripe
