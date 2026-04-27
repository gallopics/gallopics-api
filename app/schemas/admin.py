import uuid
from typing import Optional

from pydantic import BaseModel

from app.models.enums import OrderStatus


class ManualMatchRequest(BaseModel):
    equipe_id: str


class AdminOrderFilters(BaseModel):
    status: Optional[OrderStatus] = None
    user_id: Optional[uuid.UUID] = None
