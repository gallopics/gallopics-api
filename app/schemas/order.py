import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.enums import OrderStatus, PaymentTransactionStatus, PaymentTransactionType


class PaymentTransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order_id: uuid.UUID
    type: PaymentTransactionType
    status: PaymentTransactionStatus
    created_at: datetime


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    status: OrderStatus
    amount: int
    currency: str
    customer_email: Optional[str] = None
    stripe_payment_intent_id: Optional[str] = None
    transactions: list[PaymentTransactionResponse] = []
    created_at: datetime
    updated_at: datetime
