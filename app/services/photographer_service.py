import uuid
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.exceptions import ForbiddenError, NotFoundError
from app.models.enums import PhotoStatus, PhotoTagType, PhotoVisibility
from app.models.photographer import Photo, PhotoTag, Photographer
from app.storage.base import StorageBackend


class PhotographerService:
    def __init__(self, db: AsyncSession, storage: StorageBackend):
        self.db = db
        self.storage = storage

    async def get_photographer_for_user(self, user_id: uuid.UUID) -> Photographer:
        result = await self.db.execute(
            select(Photographer).where(Photographer.user_id == user_id)
        )
        photographer = result.scalar_one_or_none()
        if not photographer:
            raise NotFoundError("Photographer profile not found")
        return photographer

    async def create_upload_session(
        self,
        photographer_id: uuid.UUID,
        event_id: uuid.UUID,
        files: list[dict],
    ) -> dict:
        session_id = str(uuid.uuid4())
        uploads = []
        for f in files:
            storage_key = f"originals/{event_id}/{session_id}/{f['filename']}"
            upload_url = await self.storage.generate_presigned_upload_url(
                storage_key, f["content_type"]
            )
            uploads.append({
                "filename": f["filename"],
                "upload_url": upload_url,
                "storage_key": storage_key,
            })
        return {"session_id": session_id, "uploads": uploads}

    async def complete_upload(
        self, session_id: str, photographer_id: uuid.UUID, event_id: uuid.UUID, storage_keys: list[str], price: int = 10000
    ) -> list[Photo]:
        photos = []
        for key in storage_keys:
            photo = Photo(
                event_id=event_id,
                photographer_id=photographer_id,
                storage_key_original=key,
                price=price,
                status=PhotoStatus.PROCESSING,
                visibility=PhotoVisibility.DRAFT,
            )
            self.db.add(photo)
            photos.append(photo)
        await self.db.flush()
        return photos

    async def list_photos(
        self,
        photographer_id: uuid.UUID,
        event_id: Optional[uuid.UUID] = None,
        visibility: Optional[PhotoVisibility] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Photo], int]:
        query = (
            select(Photo)
            .where(Photo.photographer_id == photographer_id)
            .options(selectinload(Photo.tags))
        )
        if event_id:
            query = query.where(Photo.event_id == event_id)
        if visibility:
            query = query.where(Photo.visibility == visibility)

        count_query = select(func.count()).select_from(query.subquery())
        total = (await self.db.execute(count_query)).scalar_one()

        query = query.order_by(Photo.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(query)
        items = list(result.scalars().all())
        return items, total

    async def update_photo(
        self, photo_id: uuid.UUID, photographer_id: uuid.UUID, data: dict
    ) -> Photo:
        result = await self.db.execute(
            select(Photo).where(Photo.id == photo_id).options(selectinload(Photo.tags))
        )
        photo = result.scalar_one_or_none()
        if not photo:
            raise NotFoundError("Photo not found")
        if photo.photographer_id != photographer_id:
            raise ForbiddenError("Not your photo")

        if "visibility" in data and data["visibility"] is not None:
            photo.visibility = data["visibility"]
        if "price" in data and data["price"] is not None:
            photo.price = data["price"]
        if "tags" in data and data["tags"] is not None:
            # Replace all tags
            await self.db.execute(
                PhotoTag.__table__.delete().where(PhotoTag.photo_id == photo_id)
            )
            for tag in data["tags"]:
                t = PhotoTag(photo_id=photo_id, type=tag["type"], value=tag["value"])
                self.db.add(t)

        await self.db.flush()
        await self.db.refresh(photo)
        return photo

    async def delete_photo(self, photo_id: uuid.UUID, photographer_id: uuid.UUID) -> None:
        result = await self.db.execute(select(Photo).where(Photo.id == photo_id))
        photo = result.scalar_one_or_none()
        if not photo:
            raise NotFoundError("Photo not found")
        if photo.photographer_id != photographer_id:
            raise ForbiddenError("Not your photo")

        # Delete from storage
        for key in [photo.storage_key_original, photo.storage_key_preview, photo.storage_key_thumbnail]:
            if key:
                await self.storage.delete_object(key)

        await self.db.delete(photo)
        await self.db.flush()
