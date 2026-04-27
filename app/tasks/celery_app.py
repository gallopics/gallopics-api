from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "gallopics",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

celery_app.conf.beat_schedule = {
    "sync-tdb-hourly": {
        "task": "gallopics.sync_tdb",
        "schedule": crontab(minute=0),
    },
    "sync-equipe-every-30-min": {
        "task": "gallopics.sync_equipe",
        "schedule": crontab(minute="*/30"),
    },
}
