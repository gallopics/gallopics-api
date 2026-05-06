import json
import uuid
from typing import Optional

import redis.asyncio as aioredis
from fastapi import UploadFile
from slugify import slugify
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.exceptions import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.models.enums import (
    PhotographerStatus,
    PhotoStatus,
    PhotoVisibility,
    UserRole,
)
from app.models.event import Event
from app.models.photographer import Photo, Photographer, PhotographerEventBooking, PhotoTag
from app.models.user import User
from app.storage.base import StorageBackend

UPLOAD_SESSION_KEY = "upload_session:{session_id}"
UPLOAD_SESSION_TTL = 3600  # 1 hour


class PhotographerService:
    def __init__(
        self,
        db: AsyncSession,
        storage: Optional[StorageBackend] = None,
        redis: Optional[aioredis.Redis] = None,
    ):
        self.db = db
        self.storage = storage
        self.redis = redis

    async def get_photographer_for_user(self, user_id: uuid.UUID) -> Photographer:
        result = await self.db.execute(
            select(Photographer).where(Photographer.user_id == user_id)
        )
        photographer = result.scalar_one_or_none()
        if not photographer:
            raise NotFoundError("Photographer profile not found")
        return photographer

    async def get_public_photographer(self, slug_or_id: str) -> Photographer:
        photographer = None
        try:
            photographer_id = uuid.UUID(slug_or_id)
        except ValueError:
            photographer_id = None

        if photographer_id:
            photographer = await self.db.get(Photographer, photographer_id)
        if not photographer:
            result = await self.db.execute(
                select(Photographer).where(Photographer.slug == slug_or_id)
            )
            photographer = result.scalar_one_or_none()
        if not photographer:
            raise NotFoundError("Photographer profile not found")
        return photographer

    async def list_booked_events(self, photographer_id: uuid.UUID) -> list[Event]:
        result = await self.db.execute(
            select(Event)
            .join(PhotographerEventBooking, PhotographerEventBooking.event_id == Event.id)
            .where(PhotographerEventBooking.photographer_id == photographer_id)
            .order_by(Event.start_date.desc())
        )
        return list(result.scalars().all())

    async def book_event(self, photographer_id: uuid.UUID, event_id: uuid.UUID) -> Event:
        event = await self.db.get(Event, event_id)
        if not event:
            raise NotFoundError("Event not found")

        result = await self.db.execute(
            select(PhotographerEventBooking).where(
                PhotographerEventBooking.photographer_id == photographer_id,
                PhotographerEventBooking.event_id == event_id,
            )
        )
        booking = result.scalar_one_or_none()
        if not booking:
            self.db.add(
                PhotographerEventBooking(
                    photographer_id=photographer_id,
                    event_id=event_id,
                )
            )
            await self.db.flush()
        return event

    async def cancel_event_booking(self, photographer_id: uuid.UUID, event_id: uuid.UUID) -> None:
        result = await self.db.execute(
            select(PhotographerEventBooking).where(
                PhotographerEventBooking.photographer_id == photographer_id,
                PhotographerEventBooking.event_id == event_id,
            )
        )
        booking = result.scalar_one_or_none()
        if not booking:
            raise NotFoundError("Event booking not found")
        await self.db.delete(booking)
        await self.db.flush()

    async def upsert_profile(self, user: User, data: dict) -> Photographer:
        display_name = data["display_name"].strip()
        requested_slug = data.get("slug") or display_name
        profile_slug = slugify(requested_slug) or slugify(display_name)
        if not profile_slug:
            raise ConflictError("Photographer slug could not be generated")

        result = await self.db.execute(
            select(Photographer).where(Photographer.user_id == user.id)
        )
        photographer = result.scalar_one_or_none()

        slug_owner_result = await self.db.execute(
            select(Photographer).where(Photographer.slug == profile_slug)
        )
        slug_owner = slug_owner_result.scalar_one_or_none()
        if slug_owner and (not photographer or slug_owner.id != photographer.id):
            raise ConflictError("Photographer slug is already in use")

        if not photographer:
            photographer = Photographer(
                user_id=user.id,
                slug=profile_slug,
                display_name=display_name,
                status=PhotographerStatus.PENDING,
            )
            self.db.add(photographer)

        photographer.slug = profile_slug
        photographer.display_name = display_name
        photographer.city = data.get("city")
        photographer.country = data.get("country")
        photographer.avatar_url = data.get("avatar_url")
        photographer.phone = data.get("phone")
        if data.get("is_available_to_hire") is not None:
            photographer.is_available_to_hire = data["is_available_to_hire"]
        user.role = UserRole.PHOTOGRAPHER

        await self.db.flush()
        await self.db.refresh(photographer)
        return photographer

    async def upload_avatar(self, user: User, file: UploadFile) -> Photographer:
        if not file.content_type or not file.content_type.startswith("image/"):
            raise BadRequestError("Avatar must be an image file")

        extension = {
            "image/jpeg": "jpg",
            "image/png": "png",
            "image/webp": "webp",
            "image/gif": "gif",
        }.get(file.content_type, "jpg")
        storage_key = f"avatars/{user.id}/{uuid.uuid4()}.{extension}"

        result = await self.db.execute(
            select(Photographer).where(Photographer.user_id == user.id)
        )
        photographer = result.scalar_one_or_none()
        if not photographer:
            raise NotFoundError("Photographer profile not found")

        if not self.storage:
            raise BadRequestError("Storage backend not configured")

        target_path = await self.storage.write_upload_file(file, storage_key)
        photographer.avatar_url = f"/uploads/{target_path}"
        await self.db.flush()
        await self.db.refresh(photographer)
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
            if not self.storage:
                raise NotFoundError("Storage backend not configured")
            upload_url = await self.storage.generate_presigned_upload_url(storage_key, f["content_type"])
            uploads.append({
                "filename": f["filename"],
                "upload_url": upload_url,
                "storage_key": storage_key,
            })

        # Persist session data in Redis for later retrieval by complete_upload
        session_data = {
            "photographer_id": str(photographer_id),
            "event_id": str(event_id),
            "storage_keys": [u["storage_key"] for u in uploads],
            "filenames": [u["filename"] for u in uploads],
        }
        if self.redis:
            await self.redis.set(
                UPLOAD_SESSION_KEY.format(session_id=session_id),
                json.dumps(session_data, default=str),
                ex=UPLOAD_SESSION_TTL,
            )

        return {"session_id": session_id, "uploads": uploads}

    async def get_upload_session(self, session_id: str) -> dict:
        """Retrieve a persisted upload session from Redis."""
        if not self.redis:
            raise BadRequestError("Redis is not configured")
        raw = await self.redis.get(UPLOAD_SESSION_KEY.format(session_id=session_id))
        if raw is None:
            raise NotFoundError("Upload session not found or expired")
        return json.loads(raw)

    async def complete_upload(
        self,
        session_id: str,
        photographer_id: uuid.UUID,
        event_id: uuid.UUID,
        storage_keys: list[str],
        price: int = 10000,
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

    async def get_photo_by_id(self, photo_id: uuid.UUID) -> Optional[Photo]:
        result = await self.db.execute(select(Photo).where(Photo.id == photo_id))
        return result.scalar_one_or_none()
