import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class SaleItem(BaseModel):
    id: uuid.UUID
    photo_id: uuid.UUID
    event_id: uuid.UUID
    event_name: str
    class_name: Optional[str] = None
    quality: str
    # Amounts in öre
    amount: int
    photographer_amount: int
    currency: str
    sold_at: datetime
    refunded: bool
    # owed | transferred | reversed | cancelled | failed; None for sales from before payouts existed
    payout_status: Optional[str] = None


class SalesTotals(BaseModel):
    # Refunded sales are left out of every total
    count: int
    amount: int
    photographer_amount: int
    transferred: int
    owed: int


class SalesResponse(BaseModel):
    items: list[SaleItem]
    totals: SalesTotals
    commission_percent: int
    payout_day_of_month: int
