import uuid
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class LineItem(BaseModel):
    name: str
    quantity: int = Field(gt=0)
    unit_price: int = Field(ge=0)
    total_amount: int = Field(ge=0)
    reference: Optional[str] = None
    type: str = "digital"
    tax_rate: int = Field(default=0, ge=0)
    total_tax_amount: int = Field(default=0, ge=0)
    photo_id: Optional[uuid.UUID] = None
    quality: Optional[str] = None

    @model_validator(mode="after")
    def validate_total_amount(self) -> "LineItem":
        if self.total_amount != self.quantity * self.unit_price:
            raise ValueError("total_amount must equal quantity * unit_price")
        if self.total_tax_amount > self.total_amount:
            raise ValueError("total_tax_amount cannot exceed total_amount")
        return self


class CreateCheckoutSessionRequest(BaseModel):
    line_items: list[LineItem] = Field(min_length=1)
    idempotency_key: str
    purchase_country: str = "SE"
    purchase_currency: str = "SEK"
    locale: str = "sv-SE"


class CheckoutSessionResponse(BaseModel):
    session_id: str
    client_token: str
    order_id: uuid.UUID


class AuthorizeCheckoutRequest(BaseModel):
    order_id: uuid.UUID
    authorization_token: str


class PhotoDownloadRequest(BaseModel):
    order_id: uuid.UUID


class PhotoDownloadResponse(BaseModel):
    url: str
    expires_in: int = 3600
