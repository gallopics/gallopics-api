import asyncio

import structlog

from app.tasks.celery_app import celery_app

logger = structlog.get_logger()


@celery_app.task(bind=True, name="gallopics.sync_equipe", max_retries=3, default_retry_delay=60)
def sync_equipe_meetings(self):
    from app.config import get_settings
    from app.database import async_session_factory
    from app.integrations.equipe.client import EquipeClient
    from app.services.event_service import EventService

    async def _run():
        settings = get_settings()
        equipe_client = EquipeClient(settings.equipe_base_url)
        try:
            async with async_session_factory() as db:
                event_service = EventService(db)
                result = await event_service.sync_from_equipe(equipe_client, country="swe")
                await db.commit()
                return result
        finally:
            await equipe_client.close()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error("equipe_sync_task_failed", error=str(exc))
        self.retry(exc=exc)
