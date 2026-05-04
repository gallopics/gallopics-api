import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.integrations.clerk.auth import get_current_user, require_role
from app.models.enums import PhotoVisibility, UserRole
from app.models.user import User
from app.schemas import PaginatedResponse
from app.schemas.event import EventResponse
from app.schemas.photographer import (
    CompleteUploadRequest,
    CreateUploadSessionRequest,
    PhotographerResponse,
    PhotoResponse,
    UpdatePhotoRequest,
    UploadSessionResponse,
    UpsertPhotographerProfileRequest,
)
from app.services.photographer_service import PhotographerService
from app.storage.base import get_storage_backend

router = APIRouter(prefix="/api/v1/photographer", tags=["photographer"])
public_router = APIRouter(prefix="/api/v1/photographers", tags=["photographers"])


def _get_storage():
    settings = get_settings()
    return get_storage_backend(settings)


@router.get("/me", response_model=PhotographerResponse)
async def get_my_photographer_profile(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = PhotographerService(db)
    photographer = await service.get_photographer_for_user(user.id)
    return PhotographerResponse.model_validate(photographer)


@router.put("/me", response_model=PhotographerResponse)
async def upsert_my_photographer_profile(
    body: UpsertPhotographerProfileRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = PhotographerService(db)
    photographer = await service.upsert_profile(user, body.model_dump())
    return PhotographerResponse.model_validate(photographer)


@router.post("/me/avatar", response_model=PhotographerResponse)
async def upload_my_avatar(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    storage = _get_storage()
    service = PhotographerService(db, storage)
    photographer = await service.upload_avatar(user, file)
    return PhotographerResponse.model_validate(photographer)


@public_router.get("/{slug_or_id}", response_model=PhotographerResponse)
async def get_public_photographer_profile(
    slug_or_id: str,
    db: AsyncSession = Depends(get_db),
):
    service = PhotographerService(db)
    photographer = await service.get_public_photographer(slug_or_id)
    return PhotographerResponse.model_validate(photographer)


@router.get("/bookings", response_model=list[EventResponse])
async def list_my_event_bookings(
    user: User = Depends(require_role(UserRole.PHOTOGRAPHER)),
    db: AsyncSession = Depends(get_db),
):
    service = PhotographerService(db)
    photographer = await service.get_photographer_for_user(user.id)
    events = await service.list_booked_events(photographer.id)
    return [EventResponse.model_validate(event) for event in events]


@router.post("/bookings/{event_id}", response_model=EventResponse)
async def book_event(
    event_id: uuid.UUID,
    user: User = Depends(require_role(UserRole.PHOTOGRAPHER)),
    db: AsyncSession = Depends(get_db),
):
    service = PhotographerService(db)
    photographer = await service.get_photographer_for_user(user.id)
    event = await service.book_event(photographer.id, event_id)
    return EventResponse.model_validate(event)


@router.delete("/bookings/{event_id}", status_code=204)
async def cancel_event_booking(
    event_id: uuid.UUID,
    user: User = Depends(require_role(UserRole.PHOTOGRAPHER)),
    db: AsyncSession = Depends(get_db),
):
    service = PhotographerService(db)
    photographer = await service.get_photographer_for_user(user.id)
    await service.cancel_event_booking(photographer.id, event_id)


@router.post("/uploads/sessions", response_model=UploadSessionResponse)
async def create_upload_session(
    body: CreateUploadSessionRequest,
    user: User = Depends(require_role(UserRole.PHOTOGRAPHER)),
    db: AsyncSession = Depends(get_db),
):
    storage = _get_storage()
    service = PhotographerService(db, storage)
    photographer = await service.get_photographer_for_user(user.id)
    result = await service.create_upload_session(
        photographer.id, body.event_id, [f.model_dump() for f in body.files]
    )
    return UploadSessionResponse(**result)


@router.post("/uploads/complete", response_model=list[PhotoResponse])
async def complete_upload(
    body: CompleteUploadRequest,
    user: User = Depends(require_role(UserRole.PHOTOGRAPHER)),
    db: AsyncSession = Depends(get_db),
):
    storage = _get_storage()
    service = PhotographerService(db, storage)
    await service.get_photographer_for_user(user.id)
    # In production, we'd look up the session details from cache/DB
    # For now, return empty since we need the session data
    return []


@router.get("/photos", response_model=PaginatedResponse[PhotoResponse])
async def list_my_photos(
    user: User = Depends(require_role(UserRole.PHOTOGRAPHER)),
    event_id: Optional[uuid.UUID] = None,
    visibility: Optional[PhotoVisibility] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    storage = _get_storage()
    service = PhotographerService(db, storage)
    photographer = await service.get_photographer_for_user(user.id)
    items, total = await service.list_photos(
        photographer.id, event_id, visibility, page, page_size
    )
    return PaginatedResponse(
        items=[PhotoResponse.model_validate(p) for p in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.patch("/photos/{photo_id}", response_model=PhotoResponse)
async def update_photo(
    photo_id: uuid.UUID,
    body: UpdatePhotoRequest,
    user: User = Depends(require_role(UserRole.PHOTOGRAPHER)),
    db: AsyncSession = Depends(get_db),
):
    storage = _get_storage()
    service = PhotographerService(db, storage)
    photographer = await service.get_photographer_for_user(user.id)
    photo = await service.update_photo(photo_id, photographer.id, body.model_dump(exclude_unset=True))
    return PhotoResponse.model_validate(photo)


@router.delete("/photos/{photo_id}", status_code=204)
async def delete_photo(
    photo_id: uuid.UUID,
    user: User = Depends(require_role(UserRole.PHOTOGRAPHER)),
    db: AsyncSession = Depends(get_db),
):
    storage = _get_storage()
    service = PhotographerService(db, storage)
    photographer = await service.get_photographer_for_user(user.id)
    await service.delete_photo(photo_id, photographer.id)
