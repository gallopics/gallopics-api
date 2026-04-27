import asyncio
import uuid

import structlog

from app.tasks.celery_app import celery_app

logger = structlog.get_logger()


@celery_app.task(bind=True, name="gallopics.process_photo", max_retries=3, default_retry_delay=30)
def process_photo_task(self, photo_id: str):
    from app.config import get_settings
    from app.database import async_session_factory
    from app.models.photographer import Photo
    from app.services.image_processing import process_photo
    from app.storage.base import get_storage_backend

    async def _run():
        settings = get_settings()
        storage = get_storage_backend(settings)
        async with async_session_factory() as db:
            photo = await db.get(Photo, uuid.UUID(photo_id))
            if not photo:
                logger.error("photo_not_found", photo_id=photo_id)
                return
            await process_photo(photo, storage, db)
            await db.commit()

    try:
        asyncio.run(_run())
    except Exception as exc:
        logger.error("photo_processing_failed", photo_id=photo_id, error=str(exc))
        self.retry(exc=exc)
