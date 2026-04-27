import asyncio

import structlog

from app.tasks.celery_app import celery_app

logger = structlog.get_logger()


@celery_app.task(bind=True, name="gallopics.run_matching", max_retries=3, default_retry_delay=60)
def run_event_matching(self):
    from app.database import async_session_factory
    from app.services.matching_service import MatchingService

    async def _run():
        async with async_session_factory() as db:
            service = MatchingService(db)
            unmatched = await service.get_unmatched_events()
            return {"unmatched_count": len(unmatched)}

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error("matching_task_failed", error=str(exc))
        self.retry(exc=exc)
