from datetime import datetime, timezone

from app.services.photo_matching_service import PhotoMatchingService


def test_find_nearest_start_high_confidence(db_session):
    service = PhotoMatchingService(db_session, equipe_client=None)
    match = service.find_nearest_start(
        datetime(2026, 6, 3, 11, 12, 20, tzinfo=timezone.utc),
        {
            "sec_per_start": 600,
            "starts": [
                {"id": 1, "start_at": "2026-06-03T11:00:00+00:00"},
                {"id": 2, "start_at": "2026-06-03T11:10:00+00:00"},
                {"id": 3, "start_at": "2026-06-03T11:20:00+00:00"},
            ],
        },
    )

    assert match is not None
    assert match.start["id"] == 2
    assert match.delta_seconds == 140
    assert match.confidence == "high"


def test_find_nearest_start_returns_none_outside_window(db_session):
    service = PhotoMatchingService(db_session, equipe_client=None)
    match = service.find_nearest_start(
        datetime(2026, 6, 3, 11, 30, 0, tzinfo=timezone.utc),
        {
            "sec_per_start": 120,
            "starts": [
                {"id": 1, "start_at": "2026-06-03T11:00:00+00:00"},
            ],
        },
    )

    assert match is None
