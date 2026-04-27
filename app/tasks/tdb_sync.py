import asyncio

import structlog

from app.tasks.celery_app import celery_app

logger = structlog.get_logger()


@celery_app.task(bind=True, name="gallopics.sync_tdb", max_retries=3, default_retry_delay=60)
def sync_tdb_events(self):
    from app.config import get_settings
    from app.database import async_session_factory
    from app.integrations.tdb.client import TDBClient
    from app.services.event_service import EventService

    async def _run():
        settings = get_settings()
        tdb_client = TDBClient(settings.tdb_base_url)
        try:
            async with async_session_factory() as db:
                service = EventService(db)
                result = await service.sync_from_tdb(tdb_client)
                await db.commit()
                return result
        finally:
            await tdb_client.close()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error("tdb_sync_task_failed", error=str(exc))
        self.retry(exc=exc)
