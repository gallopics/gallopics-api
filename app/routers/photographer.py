import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.integrations.clerk.auth import require_role
from app.models.enums import PhotoVisibility, UserRole
from app.models.user import User
from app.schemas import PaginatedResponse
from app.schemas.photographer import (
    CompleteUploadRequest,
    CreateUploadSessionRequest,
    PhotoResponse,
    UpdatePhotoRequest,
    UploadSessionResponse,
)
from app.services.photographer_service import PhotographerService
from app.storage.base import get_storage_backend

router = APIRouter(prefix="/api/v1/photographer", tags=["photographer"])


def _get_storage():
    settings = get_settings()
    return get_storage_backend(settings)


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
    photographer = await service.get_photographer_for_user(user.id)
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
