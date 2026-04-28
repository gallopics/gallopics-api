import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.enums import OrderStatus, PhotoStatus, PhotoTagType, PhotoVisibility


class PhotoTagResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type: PhotoTagType
    value: str


class PhotoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    photographer_id: uuid.UUID
    price: int
    currency: str
    status: PhotoStatus
    visibility: PhotoVisibility
    tags: list[PhotoTagResponse] = []
    created_at: datetime
    updated_at: datetime


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


class UpdatePhotoRequest(BaseModel):
    visibility: Optional[PhotoVisibility] = None
    price: Optional[int] = None
    tags: Optional[list[PhotoTagResponse]] = None


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
