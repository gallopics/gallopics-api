import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.models.enums import OrderStatus, PhotographerStatus


class ManualMatchRequest(BaseModel):
    equipe_id: str


class AdminOrderFilters(BaseModel):
    status: Optional[OrderStatus] = None
    user_id: Optional[uuid.UUID] = None


class AdminPhotographerResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    display_name: str
    slug: str
    email: str
    city: Optional[str] = None
    country: Optional[str] = None
    avatar_url: Optional[str] = None
    # pending | approved | suspended (shown as "Rejected") — set only by admins (our database is the source of truth)
    status: str
    # not_connected | action_needed | pending | active
    stripe_status: str
    photo_count: int
    created_at: datetime


class UpdatePhotographerStatusRequest(BaseModel):
    status: PhotographerStatus
