def test_celery_app_loads():
    from app.tasks.celery_app import celery_app
    assert celery_app.main == "gallopics"


def test_beat_schedule_defined():
    from app.tasks.celery_app import celery_app
    assert "sync-tdb-hourly" in celery_app.conf.beat_schedule
    assert "sync-equipe-every-30-min" in celery_app.conf.beat_schedule


def test_tdb_sync_task_registered():
    from app.tasks.tdb_sync import sync_tdb_events
    assert sync_tdb_events.name == "gallopics.sync_tdb"


def test_equipe_sync_task_registered():
    from app.tasks.equipe_sync import sync_equipe_meetings
    assert sync_equipe_meetings.name == "gallopics.sync_equipe"


def test_matching_task_registered():
    from app.tasks.matching import run_event_matching
    assert run_event_matching.name == "gallopics.run_matching"


def test_process_photo_task_registered():
    from app.tasks.image_processing import process_photo_task
    assert process_photo_task.name == "gallopics.process_photo"
