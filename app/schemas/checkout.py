import uuid
from typing import Optional

from pydantic import BaseModel

from app.models.enums import OrderStatus


class LineItem(BaseModel):
    name: str
    quantity: int
    unit_price: int
    total_amount: int


class CreateCheckoutSessionRequest(BaseModel):
    line_items: list[LineItem]
    idempotency_key: str


class CheckoutSessionResponse(BaseModel):
    session_id: str
    client_token: str
    order_id: uuid.UUID


class AuthorizeCheckoutRequest(BaseModel):
    order_id: uuid.UUID
    authorization_token: str
