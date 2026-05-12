import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.exceptions import NotFoundError
from app.models.enums import OrderStatus, PaymentTransactionStatus, PaymentTransactionType
from app.models.order import Order, PaymentTransaction


class OrderService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_order(
        self,
        user_id: uuid.UUID,
        amount: int,
        currency: str = "SEK",
        idempotency_key: Optional[str] = None,
    ) -> Order:
        if idempotency_key:
            result = await self.db.execute(
                select(Order).where(Order.idempotency_key == idempotency_key)
            )
            existing = result.scalar_one_or_none()
            if existing:
                return existing

        order = Order(
            user_id=user_id,
            amount=amount,
            currency=currency,
            idempotency_key=idempotency_key,
        )
        self.db.add(order)
        await self.db.flush()
        return order

    async def get_order(self, order_id: uuid.UUID) -> Order:
        result = await self.db.execute(
            select(Order)
            .where(Order.id == order_id)
            .options(selectinload(Order.transactions))
            .execution_options(populate_existing=True)
        )
        order = result.scalar_one_or_none()
        if not order:
            raise NotFoundError("Order not found")
        return order

    async def list_user_orders(self, user_id: uuid.UUID) -> list[Order]:
        result = await self.db.execute(
            select(Order)
            .where(Order.user_id == user_id)
            .options(selectinload(Order.transactions))
            .order_by(Order.created_at.desc())
        )
        return list(result.scalars().all())

    async def update_order_status(self, order_id: uuid.UUID, new_status: OrderStatus) -> Order:
        order = await self.get_order(order_id)
        order.status = new_status
        await self.db.flush()
        await self.db.refresh(order)
        return order

    async def set_klarna_order_id(self, order_id: uuid.UUID, klarna_order_id: str) -> Order:
        order = await self.get_order(order_id)
        order.klarna_order_id = klarna_order_id
        await self.db.flush()
        await self.db.refresh(order)
        return order

    async def record_transaction(
        self,
        order_id: uuid.UUID,
        type_: PaymentTransactionType,
        status: PaymentTransactionStatus,
        payload: Optional[dict] = None,
    ) -> PaymentTransaction:
        txn = PaymentTransaction(
            order_id=order_id,
            type=type_,
            status=status,
            payload=payload,
        )
        self.db.add(txn)
        await self.db.flush()
        return txn
