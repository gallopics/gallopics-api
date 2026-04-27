import uuid
from typing import Optional

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import OrderStatus, PaymentTransactionStatus, PaymentTransactionType


class Order(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "orders"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[OrderStatus] = mapped_column(default=OrderStatus.PENDING)
    amount: Mapped[int] = mapped_column()
    currency: Mapped[str] = mapped_column(String, default="SEK")
    klarna_order_id: Mapped[Optional[str]] = mapped_column(String, unique=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String, unique=True, index=True)

    user: Mapped["User"] = relationship("User", back_populates="orders")
    transactions: Mapped[list["PaymentTransaction"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class PaymentTransaction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payment_transactions"

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), index=True)
    type: Mapped[PaymentTransactionType] = mapped_column()
    status: Mapped[PaymentTransactionStatus] = mapped_column()
    payload: Mapped[Optional[dict]] = mapped_column(JSON)

    order: Mapped["Order"] = relationship(back_populates="transactions")
