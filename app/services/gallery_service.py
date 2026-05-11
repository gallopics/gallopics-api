import uuid
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.exceptions import NotFoundError
from app.models.enums import PhotoStatus, PhotoVisibility
from app.models.photographer import Photo, PhotoTag
from app.storage.base import StorageBackend


class GalleryService:
    def __init__(self, db: AsyncSession, storage: Optional[StorageBackend] = None):
        self.db = db
        self.storage = storage

    async def get_event_gallery(
        self,
        event_id: uuid.UUID,
        page: int = 1,
        page_size: int = 20,
        class_id: Optional[str] = None,
    ) -> tuple[list[Photo], int]:
        query = (
            select(Photo)
            .where(
                Photo.event_id == event_id,
                Photo.visibility == PhotoVisibility.PUBLISHED,
                Photo.status == PhotoStatus.READY,
            )
            .options(selectinload(Photo.tags))
        )
        if class_id:
            try:
                class_uuid = uuid.UUID(class_id)
            except ValueError:
                query = query.where(Photo.event_class_id == class_id)
            else:
                query = query.where(
                    (Photo.class_id == class_uuid)
                    | (Photo.class_section_id == class_uuid)
                    | (Photo.event_class_id == class_id)
                )

        count_query = select(func.count()).select_from(query.subquery())
        total = (await self.db.execute(count_query)).scalar_one()

        query = query.order_by(Photo.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(query)
        items = list(result.scalars().all())
        return items, total

    async def search_event_gallery(
        self,
        event_id: uuid.UUID,
        query_str: str,
        tag_type: Optional[str] = None,
        class_id: Optional[str] = None,
    ) -> list[Photo]:
        query = (
            select(Photo)
            .join(PhotoTag, PhotoTag.photo_id == Photo.id)
            .where(
                Photo.event_id == event_id,
                Photo.visibility == PhotoVisibility.PUBLISHED,
                Photo.status == PhotoStatus.READY,
                PhotoTag.value.ilike(f"%{query_str}%"),
            )
            .options(selectinload(Photo.tags))
        )
        if tag_type:
            query = query.where(PhotoTag.type == tag_type)
        if class_id:
            try:
                class_uuid = uuid.UUID(class_id)
            except ValueError:
                query = query.where(Photo.event_class_id == class_id)
            else:
                query = query.where(
                    (Photo.class_id == class_uuid)
                    | (Photo.class_section_id == class_uuid)
                    | (Photo.event_class_id == class_id)
                )

        result = await self.db.execute(query)
        return list(result.scalars().unique().all())

    async def get_photo_detail(self, photo_id: uuid.UUID) -> Photo:
        result = await self.db.execute(
            select(Photo)
            .where(
                Photo.id == photo_id,
                Photo.visibility == PhotoVisibility.PUBLISHED,
                Photo.status == PhotoStatus.READY,
            )
            .options(selectinload(Photo.tags))
        )
        photo = result.scalar_one_or_none()
        if not photo:
            raise NotFoundError("Photo not found")
        return photo
