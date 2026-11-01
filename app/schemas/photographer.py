import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.models.enums import OrderStatus, PhotoStatus, PhotoTagType, PhotoVisibility
from app.services.pricing import validate_price


class PhotoTagResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type: PhotoTagType
    value: str


class PhotoPrices(BaseModel):
    """Price per quality tier, in öre."""

    web: int
    high: int
    commercial: int


class PhotoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    class_id: Optional[uuid.UUID] = None
    class_section_id: Optional[uuid.UUID] = None
    event_class_id: Optional[str] = None
    equipe_class_section_id: Optional[str] = None
    class_name: Optional[str] = None
    photographer_id: uuid.UUID
    photographer_display_name: Optional[str] = None
    photographer_avatar_url: Optional[str] = None
    prices: PhotoPrices
    currency: str
    status: PhotoStatus
    visibility: PhotoVisibility
    tags: list[PhotoTagResponse] = []
    storage_key_original: Optional[str] = None
    storage_key_thumbnail: Optional[str] = None
    storage_key_preview: Optional[str] = None
    taken_at: Optional[datetime] = None
    equipe_start_id: Optional[str] = None
    equipe_rider_id: Optional[str] = None
    equipe_horse_id: Optional[str] = None
    matched_at: Optional[datetime] = None
    match_confidence: Optional[str] = None
    match_delta_seconds: Optional[int] = None
    match_source: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("taken_at", "matched_at", when_used="json")
    def serialize_optional_utc_datetime(self, value: Optional[datetime]) -> Optional[str]:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        return value.isoformat().replace("+00:00", "Z")


class PhotographerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    slug: str
    display_name: str
    city: Optional[str] = None
    country: Optional[str] = None
    avatar_url: Optional[str] = None
    phone: Optional[str] = None
    is_available_to_hire: bool
    highlights: list[str] = []
    status: str
    created_at: datetime
    updated_at: datetime


class UpsertPhotographerProfileRequest(BaseModel):
    slug: Optional[str] = None
    display_name: str
    city: Optional[str] = None
    country: Optional[str] = None
    avatar_url: Optional[str] = None
    phone: Optional[str] = None
    is_available_to_hire: Optional[bool] = None


class FileInfo(BaseModel):
    filename: str
    content_type: str


class CreateUploadSessionRequest(BaseModel):
    event_id: uuid.UUID
    class_id: Optional[uuid.UUID] = None
    class_section_id: Optional[uuid.UUID] = None
    event_class_id: Optional[str] = None
    equipe_class_section_id: Optional[str] = None
    class_name: Optional[str] = None
    taken_at: Optional[datetime] = None
    files: list[FileInfo]


class PresignedUploadURL(BaseModel):
    filename: str
    upload_url: str
    storage_key: str


class UploadSessionResponse(BaseModel):
    session_id: str
    uploads: list[PresignedUploadURL]


class CompleteUploadRequest(BaseModel):
    session_id: str


class UpdatePhotoPricesFields(BaseModel):
    """New prices in öre; tiers left out keep their price."""

    web: Optional[int] = None
    high: Optional[int] = None
    commercial: Optional[int] = None

    @field_validator("web", "high", "commercial")
    @classmethod
    def validate_amount(cls, value: Optional[int]) -> Optional[int]:
        return None if value is None else validate_price(value)


class UpdatePhotoRequest(BaseModel):
    visibility: Optional[PhotoVisibility] = None
    prices: Optional[UpdatePhotoPricesFields] = None
    tags: Optional[list[PhotoTagResponse]] = None


class UpdatePhotoPricesRequest(BaseModel):
    """The same prices for several photos at once."""

    photo_ids: list[uuid.UUID] = Field(min_length=1, max_length=1000)
    prices: UpdatePhotoPricesFields


class HighlightsResponse(BaseModel):
    highlights: list[str]


class UpdateHighlightsRequest(BaseModel):
    photo_ids: list[str]


class PhotoOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    photo_id: uuid.UUID
    amount: int
    currency: str
    status: OrderStatus
    klarna_order_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
