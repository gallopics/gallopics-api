import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.enums import PhotoTagType
from app.schemas import PaginatedResponse
from app.schemas.photographer import PhotoResponse
from app.services.gallery_service import GalleryService

router = APIRouter(tags=["gallery"])


@router.get("/api/v1/events/{event_id}/gallery", response_model=PaginatedResponse[PhotoResponse])
async def get_gallery(
    event_id: uuid.UUID,
    class_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    service = GalleryService(db)
    items, total = await service.get_event_gallery(event_id, page, page_size, class_id)
    return PaginatedResponse(
        items=[PhotoResponse.model_validate(p) for p in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/api/v1/events/{event_id}/gallery/search", response_model=list[PhotoResponse])
async def search_gallery(
    event_id: uuid.UUID,
    q: str = Query(...),
    tag_type: Optional[PhotoTagType] = None,
    class_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    service = GalleryService(db)
    photos = await service.search_event_gallery(event_id, q, tag_type, class_id)
    return [PhotoResponse.model_validate(p) for p in photos]


@router.get("/api/v1/photos/{photo_id}", response_model=PhotoResponse)
async def get_photo(photo_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    service = GalleryService(db)
    photo = await service.get_photo_detail(photo_id)
    return PhotoResponse.model_validate(photo)
