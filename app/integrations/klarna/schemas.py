from typing import Optional

from pydantic import BaseModel


class KlarnaSessionRequest(BaseModel):
    purchase_country: str = "SE"
    purchase_currency: str = "SEK"
    locale: str = "sv-SE"
    order_amount: int
    order_lines: list[dict]


class KlarnaSessionResponse(BaseModel):
    session_id: str
    client_token: str


class KlarnaOrderResponse(BaseModel):
    order_id: str
    fraud_status: Optional[str] = None
