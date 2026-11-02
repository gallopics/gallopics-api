import re
import uuid
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.enums import OrderStatus

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# "/photo/1?from=epro" yes; "//evil.com", "/\evil.com", "https://..." no
_SITE_PATH_PATTERN = re.compile(r"^/(?![/\\])[^\s\\]*$")


class CheckoutItem(BaseModel):
    photo_id: uuid.UUID
    quality: str


class CreateCheckoutSessionRequest(BaseModel):
    # Prices are looked up by the server; the client only says what to buy
    items: list[CheckoutItem] = Field(min_length=1, max_length=100)
    customer_email: str
    # Where "back" on Stripe's page returns to; a path on our own site only
    cancel_path: Optional[str] = Field(default=None, max_length=500)

    @field_validator("cancel_path")
    @classmethod
    def validate_cancel_path(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not _SITE_PATH_PATTERN.match(value):
            raise ValueError("cancel_path must be a path on this site, like /photo/123")
        return value

    @field_validator("customer_email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        value = value.strip()
        if not _EMAIL_PATTERN.match(value):
            raise ValueError("A valid email is required for the receipt")
        return value


class CheckoutSessionResponse(BaseModel):
    order_id: uuid.UUID
    session_id: str
    checkout_url: str


class CheckoutOrderItem(BaseModel):
    photo_id: uuid.UUID
    quality: str
    name: str
    amount: int
    thumbnail_url: Optional[str] = None


class CheckoutOrderResponse(BaseModel):
    order_id: uuid.UUID
    status: OrderStatus
    paid: bool
    customer_email: Optional[str] = None
    amount: int
    currency: str
    items: list[CheckoutOrderItem]


class PhotoDownloadRequest(BaseModel):
    order_id: uuid.UUID


class PhotoDownloadResponse(BaseModel):
    url: str
    expires_in: int = 3600
