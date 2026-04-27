import asyncio

import structlog

from app.tasks.celery_app import celery_app

logger = structlog.get_logger()


@celery_app.task(bind=True, name="gallopics.sync_equipe", max_retries=3, default_retry_delay=60)
def sync_equipe_meetings(self):
    from app.config import get_settings
    from app.database import async_session_factory
    from app.integrations.equipe.client import EquipeClient
    from app.integrations.equipe.normalizer import normalize_equipe_meeting
    from app.services.matching_service import MatchingService

    async def _run():
        settings = get_settings()
        equipe_client = EquipeClient(settings.equipe_base_url)
        try:
            raw_meetings = await equipe_client.get_meetings()
            normalized = [normalize_equipe_meeting(m) for m in raw_meetings]
            async with async_session_factory() as db:
                matching_service = MatchingService(db)
                result = await matching_service.run_matching_batch(normalized)
                await db.commit()
                return result
        finally:
            await equipe_client.close()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error("equipe_sync_task_failed", error=str(exc))
        self.retry(exc=exc)
