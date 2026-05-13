import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.exceptions import BadRequestError, ForbiddenError, NotFoundError
from app.models.enums import OrderStatus, PhotoTagType
from app.models.order import Order
from app.models.photographer import PhotoPurchase
from app.schemas import PaginatedResponse
from app.schemas.checkout import PhotoDownloadRequest, PhotoDownloadResponse
from app.schemas.photographer import PhotoResponse
from app.services.gallery_service import GalleryService
from app.storage.base import get_storage_backend

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


@router.post("/api/v1/photos/{photo_id}/download", response_model=PhotoDownloadResponse)
async def create_photo_download(
    photo_id: uuid.UUID,
    body: PhotoDownloadRequest,
    db: AsyncSession = Depends(get_db),
):
    order = await db.get(Order, body.order_id)
    if not order:
        raise NotFoundError("Order not found")
    if order.status != OrderStatus.CAPTURED:
        raise ForbiddenError("Order is not captured")

    result = await db.execute(
        select(PhotoPurchase)
        .where(PhotoPurchase.order_id == order.id, PhotoPurchase.photo_id == photo_id)
        .join(PhotoPurchase.photo)
    )
    purchase = result.scalar_one_or_none()
    if not purchase:
        raise ForbiddenError("This order does not include the requested photo")
    if not purchase.photo.storage_key_original:
        raise BadRequestError("Original file is not available")

    storage = get_storage_backend(get_settings())
    url = await storage.generate_presigned_download_url(
        purchase.photo.storage_key_original,
        expires_in=3600,
    )
    return PhotoDownloadResponse(url=url, expires_in=3600)
