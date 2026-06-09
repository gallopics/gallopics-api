from datetime import datetime, timezone

from app.models.event import Event
from app.models.photographer import Photo
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


async def test_match_photo_resolves_meeting_class_id_to_nearest_section(db_session):
    class FakeEquipeClient:
        async def get_meeting_schedule(self, meeting_id):
            assert meeting_id == "79213"
            return {
                "meeting_classes": [
                    {
                        "id": 1208737,
                        "equipe_id": 11,
                        "class_no": "11",
                        "class_sections": [
                            {"id": 1236758},
                            {"id": 1235201},
                        ],
                    }
                ]
            }

        async def get_class_section(self, class_section_id):
            if class_section_id == "1236758":
                return {
                    "sec_per_start": 135,
                    "starts": [
                        {
                            "id": 1,
                            "start_at": "2026-05-17T12:17:30+02:00",
                            "rider_id": 6359431,
                            "horse_id": 7739821,
                            "start_no": "1",
                            "rider_name": "Amanda Helgemo",
                            "horse_name": "Cortina D'Ampezzo",
                        }
                    ],
                }
            return {
                "sec_per_start": 134,
                "starts": [
                    {
                        "id": 2,
                        "start_at": "2026-05-17T12:28:00+02:00",
                        "rider_id": 1,
                        "horse_id": 2,
                        "start_no": "2",
                        "rider_name": "Other Rider",
                        "horse_name": "Other Horse",
                    }
                ],
            }

    event = Event(
        name="Ängelholms Ryttarförening",
        slug="angelholms",
        start_date=datetime(2026, 5, 16).date(),
        country="SWE",
        raw_equipe_payload={"id": 79213},
    )
    photo = Photo(
        event_id=event.id,
        photographer_id=event.id,
        storage_key_original="originals/test.jpg",
        price=10000,
        equipe_class_section_id="1208737",
        taken_at=datetime(2026, 5, 17, 12, 15, 40, tzinfo=timezone.utc),
    )
    db_session.add(event)
    db_session.add(photo)
    await db_session.flush()

    match = await PhotoMatchingService(db_session, FakeEquipeClient()).match_photo(
        photo,
        event,
    )

    assert match is not None
    assert photo.equipe_class_section_id == "1236758"
    assert photo.equipe_rider_id == "6359431"
    assert photo.equipe_horse_id == "7739821"
    assert photo.match_confidence == "high"
