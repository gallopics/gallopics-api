import uuid
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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
from app.services.download_service import download_bytes
from app.services.pricing import get_quality_tier
from app.storage.base import get_storage_backend

router = APIRouter(tags=["gallery"])


@router.get("/api/v1/events/{event_id}/gallery", response_model=PaginatedResponse[PhotoResponse])
async def get_gallery(
    event_id: uuid.UUID,
    class_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db, scope="function"),
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
    db: AsyncSession = Depends(get_db, scope="function"),
):
    service = GalleryService(db)
    photos = await service.search_event_gallery(event_id, q, tag_type, class_id)
    return [PhotoResponse.model_validate(p) for p in photos]


@router.get("/api/v1/photos/{photo_id}", response_model=PhotoResponse)
async def get_photo(photo_id: uuid.UUID, db: AsyncSession = Depends(get_db, scope="function")):
    service = GalleryService(db)
    photo = await service.get_photo_detail(photo_id)
    return PhotoResponse.model_validate(photo)


async def _get_captured_photo_purchase(
    photo_id: uuid.UUID,
    order_id: uuid.UUID,
    db: AsyncSession,
    quality: str | None = None,
) -> PhotoPurchase:
    order = await db.get(Order, order_id)
    if not order:
        raise NotFoundError("Order not found")
    if order.status != OrderStatus.CAPTURED:
        raise ForbiddenError("Order is not captured")

    query = (
        select(PhotoPurchase)
        .options(selectinload(PhotoPurchase.photo))
        .where(PhotoPurchase.order_id == order.id, PhotoPurchase.photo_id == photo_id)
    )
    if quality is not None:
        get_quality_tier(quality)
        query = query.where(PhotoPurchase.quality == quality)
    result = await db.execute(query)
    purchases = result.scalars().all()
    if len(purchases) > 1:
        raise BadRequestError("Choose the quality to download")
    purchase = purchases[0] if purchases else None
    if not purchase:
        raise ForbiddenError("This order does not include the requested photo")
    if not purchase.photo.storage_key_original:
        raise BadRequestError("Original file is not available")

    return purchase


@router.post("/api/v1/photos/{photo_id}/download", response_model=PhotoDownloadResponse)
async def create_photo_download(
    photo_id: uuid.UUID,
    body: PhotoDownloadRequest,
    request: Request,
    db: AsyncSession = Depends(get_db, scope="function"),
):
    purchase = await _get_captured_photo_purchase(photo_id, body.order_id, db, body.quality)
    url = request.url_for("download_photo_file", photo_id=str(photo_id)).include_query_params(
        order_id=str(body.order_id), quality=purchase.quality
    )
    return PhotoDownloadResponse(url=str(url), expires_in=3600)


@router.get("/api/v1/photos/{photo_id}/download", include_in_schema=False)
async def download_photo_file(
    photo_id: uuid.UUID,
    order_id: uuid.UUID,
    inline: bool = Query(False),
    quality: str | None = Query(None),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    purchase = await _get_captured_photo_purchase(photo_id, order_id, db, quality)
    storage = get_storage_backend(get_settings())

    data = await download_bytes(purchase.photo, get_quality_tier(purchase.quality), storage)

    filename = f"gallopics-{photo_id}.jpg"
    disposition = "inline" if inline else "attachment"
    return StreamingResponse(
        BytesIO(data),
        media_type="image/jpeg" if inline else "application/octet-stream",
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )
