import uuid
from datetime import datetime
from typing import Optional

from dateutil.parser import parse as parse_date
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from PIL import UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.database import get_db
from app.exceptions import BadRequestError, ForbiddenError, NotFoundError
from app.integrations.clerk.auth import get_current_user, require_role
from app.integrations.equipe.client import EquipeClient
from app.models.enums import PhotoVisibility, UserRole
from app.models.event import Event
from app.models.photographer import Photo
from app.models.user import User
from app.schemas import PaginatedResponse
from app.schemas.event import EventResponse
from app.schemas.photographer import (
    CompleteUploadRequest,
    CreateUploadSessionRequest,
    HighlightsResponse,
    PhotographerResponse,
    PhotoResponse,
    UpdateHighlightsRequest,
    UpdatePhotoRequest,
    UploadSessionResponse,
    UpsertPhotographerProfileRequest,
)
from app.services.photo_matching_service import PhotoMatchingService
from app.services.photographer_service import PhotographerService
from app.storage.base import get_storage_backend

router = APIRouter(prefix="/api/v1/photographer", tags=["photographer"])
public_router = APIRouter(prefix="/api/v1/photographers", tags=["photographers"])


def _get_storage():
    settings = get_settings()
    return get_storage_backend(settings)


async def _validate_upload_file_size(file: UploadFile, max_size_bytes: int) -> None:
    size = 0
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > max_size_bytes:
            await file.seek(0)
            max_size_mb = max_size_bytes // (1024 * 1024)
            raise BadRequestError(
                f"File '{file.filename}' is too large. Maximum upload size is {max_size_mb} MB."
            )
    await file.seek(0)


async def _photo_responses(db: AsyncSession, photos) -> list[PhotoResponse]:
    photo_ids = [photo.id for photo in photos]
    result = await db.execute(
        select(Photo)
        .where(Photo.id.in_(photo_ids))
        .options(selectinload(Photo.tags), selectinload(Photo.photographer))
    )
    photos_by_id = {photo.id: photo for photo in result.scalars().all()}
    return [
        PhotoResponse.model_validate(photos_by_id.get(photo.id, photo))
        for photo in photos
    ]


def _parse_optional_datetime(value: Optional[str], field_name: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return parse_date(value)
    except (TypeError, ValueError) as exc:
        raise BadRequestError(f"Invalid {field_name}") from exc


async def _match_uploaded_photos(db: AsyncSession, photos: list[Photo], event_id: uuid.UUID) -> None:
    settings = get_settings()
    if not settings.equipe_base_url:
        return

    event = await db.get(Event, event_id)
    if not event:
        return

    equipe_client = EquipeClient(settings.equipe_base_url)
    try:
        matcher = PhotoMatchingService(db, equipe_client)
        for photo in photos:
            await matcher.try_match_photo(photo, event)
    finally:
        await equipe_client.close()


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


@router.get("/highlights", response_model=HighlightsResponse)
async def get_highlights(
    user: User = Depends(require_role(UserRole.PHOTOGRAPHER)),
    db: AsyncSession = Depends(get_db),
):
    service = PhotographerService(db)
    photographer = await service.get_photographer_for_user(user.id)
    return HighlightsResponse(highlights=photographer.highlights or [])


@router.put("/highlights", response_model=HighlightsResponse)
async def update_highlights(
    body: UpdateHighlightsRequest,
    user: User = Depends(require_role(UserRole.PHOTOGRAPHER)),
    db: AsyncSession = Depends(get_db),
):
    service = PhotographerService(db)
    photographer = await service.get_photographer_for_user(user.id)
    photographer = await service.update_highlights(photographer, body.photo_ids)
    return HighlightsResponse(highlights=photographer.highlights or [])


@public_router.get("/{slug_or_id}/highlights", response_model=HighlightsResponse)
async def get_public_photographer_highlights(
    slug_or_id: str,
    db: AsyncSession = Depends(get_db),
):
    service = PhotographerService(db)
    photographer = await service.get_public_photographer(slug_or_id)
    return HighlightsResponse(highlights=photographer.highlights or [])


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
        photographer.id,
        body.event_id,
        [f.model_dump() for f in body.files],
        body.class_id,
        body.class_section_id,
        body.event_class_id,
        body.equipe_class_section_id,
        body.class_name,
        body.taken_at,
    )
    return UploadSessionResponse(**result)


@router.post("/uploads", response_model=list[PhotoResponse])
async def upload_photos(
    event_id: str = Form(...),
    class_id: Optional[str] = Form(None),
    class_section_id: Optional[str] = Form(None),
    event_class_id: Optional[str] = Form(None),
    equipe_class_section_id: Optional[str] = Form(None),
    class_name: Optional[str] = Form(None),
    taken_at: Optional[str] = Form(None),
    files: list[UploadFile] = File(...),
    user: User = Depends(require_role(UserRole.PHOTOGRAPHER)),
    db: AsyncSession = Depends(get_db),
):
    """Direct multipart upload endpoint for browser integration.

    Accepts files via FormData with:
    - event_id: the event UUID (string)
    - files: one or more image files

    Returns PhotoResponse objects for each uploaded photo.
    """
    import uuid as _uuid

    storage = _get_storage()
    service = PhotographerService(db, storage)
    photographer = await service.get_photographer_for_user(user.id)

    # Validate files
    settings = get_settings()
    max_upload_size_bytes = settings.max_upload_file_size_mb * 1024 * 1024
    valid_files = []
    for file in files:
        if file.content_type and file.content_type.startswith("image/"):
            await _validate_upload_file_size(file, max_upload_size_bytes)
            valid_files.append(file)
        else:
            raise BadRequestError(f"File '{file.filename}' is not an image")

    if not valid_files:
        raise BadRequestError("No valid image files provided")

    # Create upload session internally
    session_id = str(_uuid.uuid4())
    try:
        event_uuid = _uuid.UUID(event_id)
    except ValueError as exc:
        raise BadRequestError("Invalid event_id") from exc

    class_uuid = None
    class_section_uuid = None
    external_class_section_id = equipe_class_section_id
    if class_id:
        try:
            class_uuid = _uuid.UUID(class_id)
        except ValueError as exc:
            raise BadRequestError("Invalid class_id") from exc
    if class_section_id:
        try:
            class_section_uuid = _uuid.UUID(class_section_id)
        except ValueError:
            external_class_section_id = class_section_id

    parsed_taken_at = _parse_optional_datetime(taken_at, "taken_at")

    # Save files to storage
    storage_keys = []
    for file in valid_files:
        storage_key = f"originals/{event_id}/{session_id}/{file.filename}"
        await storage.write_upload_file(file, storage_key)
        storage_keys.append(storage_key)

    # Create Photo records
    photos = await service.complete_upload(
        session_id=session_id,
        photographer_id=photographer.id,
        event_id=event_uuid,
        storage_keys=storage_keys,
        class_id=class_uuid,
        class_section_id=class_section_uuid or class_uuid,
        event_class_id=event_class_id,
        equipe_class_section_id=external_class_section_id,
        class_name=class_name,
        taken_at=parsed_taken_at,
    )

    # Trigger image processing (thumbnails, previews, watermark)
    from app.services.image_processing import process_photo

    try:
        for photo in photos:
            await process_photo(photo, storage, db)
    except (OSError, UnidentifiedImageError) as exc:
        raise BadRequestError("One or more uploaded files are not supported image formats") from exc

    await _match_uploaded_photos(db, photos, event_uuid)
    await db.flush()

    return await _photo_responses(db, photos)


@router.post("/uploads/complete", response_model=list[PhotoResponse])
async def complete_upload(
    body: CompleteUploadRequest,
    user: User = Depends(require_role(UserRole.PHOTOGRAPHER)),
    db: AsyncSession = Depends(get_db),
):
    storage = _get_storage()
    from app.redis import get_redis

    redis_client = await get_redis()
    service = PhotographerService(db, storage, redis_client)
    photographer = await service.get_photographer_for_user(user.id)

    # Retrieve session data from Redis
    session_data = await service.get_upload_session(body.session_id)

    # Verify photographer matches
    if session_data["photographer_id"] != str(photographer.id):
        raise ForbiddenError("Session does not belong to this photographer")

    event_id = uuid.UUID(session_data["event_id"])
    class_id = uuid.UUID(session_data["class_id"]) if session_data.get("class_id") else None
    class_section_id = (
        uuid.UUID(session_data["class_section_id"])
        if session_data.get("class_section_id")
        else None
    )
    taken_at = _parse_optional_datetime(session_data.get("taken_at"), "taken_at")
    storage_keys = session_data["storage_keys"]

    # Create Photo records
    photos = await service.complete_upload(
        session_id=body.session_id,
        photographer_id=photographer.id,
        event_id=event_id,
        storage_keys=storage_keys,
        class_id=class_id,
        class_section_id=class_section_id,
        event_class_id=session_data.get("event_class_id"),
        equipe_class_section_id=session_data.get("equipe_class_section_id"),
        class_name=session_data.get("class_name"),
        taken_at=taken_at,
    )

    # Commit the transaction so photos are queryable
    await db.flush()

    # Trigger async image processing
    from app.services.image_processing import process_photo

    try:
        for photo in photos:
            await process_photo(photo, storage, db)
    except (OSError, UnidentifiedImageError) as exc:
        raise BadRequestError("One or more uploaded files are not supported image formats") from exc

    await _match_uploaded_photos(db, photos, event_id)
    await db.flush()

    return await _photo_responses(db, photos)


@router.get("/photos", response_model=PaginatedResponse[PhotoResponse])
async def list_my_photos(
    user: User = Depends(require_role(UserRole.PHOTOGRAPHER)),
    event_id: Optional[uuid.UUID] = None,
    class_id: Optional[str] = None,
    visibility: Optional[PhotoVisibility] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    storage = _get_storage()
    service = PhotographerService(db, storage)
    photographer = await service.get_photographer_for_user(user.id)
    items, total = await service.list_photos(
        photographer.id, event_id, class_id, visibility, page, page_size
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


@router.get("/photos/{photo_id}/preview", include_in_schema=False)
async def get_photo_preview(
    photo_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Serve a photo preview/thumbnail from storage."""
    from io import BytesIO

    from fastapi.responses import StreamingResponse

    service = PhotographerService(db)
    photo = await service.get_photo_by_id(photo_id)
    if not photo:
        raise NotFoundError("Photo not found")

    storage_key = photo.storage_key_preview or photo.storage_key_original
    storage = _get_storage()

    # Download from storage
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_path = f"{tmpdir}/photo.jpg"
        await storage.download_to_path(storage_key, temp_path)
        with open(temp_path, "rb") as f:
            data = f.read()

    return StreamingResponse(
        BytesIO(data),
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=31536000"},
    )


@router.get("/photos/{photo_id}/thumbnail", include_in_schema=False)
async def get_photo_thumbnail(
    photo_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Serve a photo thumbnail from storage."""
    from io import BytesIO

    from fastapi.responses import StreamingResponse

    service = PhotographerService(db)
    photo = await service.get_photo_by_id(photo_id)
    if not photo:
        raise NotFoundError("Photo not found")

    storage_key = photo.storage_key_thumbnail
    if not storage_key:
        # Fallback to original if no thumbnail exists
        storage_key = photo.storage_key_original
    storage = _get_storage()

    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_path = f"{tmpdir}/photo.jpg"
        await storage.download_to_path(storage_key, temp_path)
        with open(temp_path, "rb") as f:
            data = f.read()

    return StreamingResponse(
        BytesIO(data),
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=31536000"},
    )


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
