import uuid
from datetime import date

import pytest

from app.exceptions import NotFoundError
from app.schemas.event import EventFilters
from app.services.event_service import EventService
from tests.factories import make_event


@pytest.fixture
def service(db_session):
    return EventService(db_session)


async def test_create_event(service, db_session):
    data = make_event(name="Grand Prix")
    event = await service.create_event(data)
    assert event.name == "Grand Prix"
    assert event.id is not None


async def test_create_event_generates_slug(service):
    data = make_event(name="Stockholm Open", slug=None)
    event = await service.create_event(data)
    assert "stockholm-open" in event.slug


async def test_get_event_by_id(service):
    data = make_event()
    created = await service.create_event(data)
    found = await service.get_event(created.id)
    assert found.id == created.id


async def test_get_event_by_id_not_found(service):
    with pytest.raises(NotFoundError):
        await service.get_event(uuid.uuid4())


async def test_get_event_by_slug(service):
    data = make_event(slug="unique-slug-123")
    await service.create_event(data)
    found = await service.get_event_by_slug("unique-slug-123")
    assert found.slug == "unique-slug-123"


async def test_list_events_empty(service):
    items, total = await service.list_events(EventFilters())
    assert items == []
    assert total == 0


async def test_list_events_with_data(service):
    for i in range(3):
        await service.create_event(make_event(name=f"Event {i}"))
    items, total = await service.list_events(EventFilters())
    assert total == 3
    assert len(items) == 3


async def test_list_events_filter_by_discipline(service):
    await service.create_event(make_event(discipline="dressage"))
    await service.create_event(make_event(discipline="jumping"))
    items, total = await service.list_events(EventFilters(discipline="dressage"))
    assert total == 1
    assert items[0].discipline == "dressage"


async def test_list_events_filter_by_date_range(service):
    await service.create_event(make_event(start_date=date(2026, 1, 10)))
    await service.create_event(make_event(start_date=date(2026, 6, 15)))
    await service.create_event(make_event(start_date=date(2026, 12, 1)))
    items, total = await service.list_events(
        EventFilters(date_from=date(2026, 6, 1), date_to=date(2026, 6, 30))
    )
    assert total == 1


async def test_list_events_pagination(service):
    for i in range(25):
        await service.create_event(make_event(name=f"Event {i}", start_date=date(2026, 1, i + 1)))
    items, total = await service.list_events(EventFilters(), page=2, page_size=10)
    assert total == 25
    assert len(items) == 10


async def test_upsert_event_by_tdb_id_creates_new(service):
    data = make_event(name="New Event")
    event, is_new = await service.upsert_event_by_tdb_id("tdb-001", data)
    assert is_new is True
    assert event.tdb_id == "tdb-001"


async def test_upsert_event_by_tdb_id_updates_existing(service):
    data = make_event(name="Original")
    event1, _ = await service.upsert_event_by_tdb_id("tdb-002", data)

    data2 = make_event(name="Updated")
    event2, is_new = await service.upsert_event_by_tdb_id("tdb-002", data2)
    assert is_new is False
    assert event2.name == "Updated"
    assert event2.id == event1.id


async def test_upsert_event_by_equipe_id_creates_new(service):
    data = make_event(name="Equipe Event", country="SWE")
    event, is_new = await service.upsert_event_by_equipe_id("90019", data)
    assert is_new is True
    assert event.equipe_id == "90019"
    assert event.name == "Equipe Event"


async def test_upsert_event_by_equipe_id_updates_existing_tdb_event(service):
    event1, _ = await service.upsert_event_by_tdb_id("8223", make_event(name="TDB Event"))

    data = make_event(name="Equipe Event", tdb_id="8223", country="SWE")
    event2, is_new = await service.upsert_event_by_equipe_id("90019", data)

    assert is_new is False
    assert event2.id == event1.id
    assert event2.equipe_id == "90019"
    assert event2.name == "Equipe Event"


async def test_sync_from_tdb_returns_error_samples(service):
    class FakeTDBClient:
        async def search_events(self):
            return [{"id": "tdb-bad", "name": "Bad Event", "start_date": None}]

    result = await service.sync_from_tdb(FakeTDBClient())

    assert result["created"] == 0
    assert result["updated"] == 0
    assert result["errors"] == 1
    assert result["error_samples"][0]["tdb_id"] == "tdb-bad"
    assert result["error_samples"][0]["name"] == "Bad Event"
    assert result["error_samples"][0]["error"]


async def test_sync_from_equipe_populates_events_table(service):
    class FakeEquipeClient:
        async def get_meetings(self, params=None):
            assert params == {"country": "swe"}
            return [
                {
                    "id": 78298,
                    "display_name": "Swedish Dressage",
                    "start_on": "2026-05-13",
                    "equipe_id": 90019,
                    "venue_country": "SWE",
                    "discipline": "dressage",
                }
            ]

    result = await service.sync_from_equipe(FakeEquipeClient())

    assert result["created"] == 1
    assert result["updated"] == 0
    items, total = await service.list_events(EventFilters())
    assert total == 1
    assert items[0].equipe_id == "90019"
    assert items[0].country == "SWE"


async def test_sync_from_equipe_skips_non_swedish_meetings(service):
    class FakeEquipeClient:
        async def get_meetings(self, params=None):
            return [
                {
                    "id": 78298,
                    "display_name": "British Dressage",
                    "start_on": "2026-05-13",
                    "equipe_id": 90019,
                    "venue_country": "GBR",
                }
            ]

    result = await service.sync_from_equipe(FakeEquipeClient())

    assert result["created"] == 0
    assert result["skipped"] == 1


async def test_update_event(service):
    event = await service.create_event(make_event(name="Old Name"))
    updated = await service.update_event(event.id, {"name": "New Name"})
    assert updated.name == "New Name"


async def test_get_event_results_empty(service):
    event = await service.create_event(make_event())
    results = await service.get_event_results(event.id)
    assert results == []


async def test_upsert_event_results(service):
    event = await service.create_event(make_event())
    results = await service.upsert_event_results(event.id, [
        {"participant_name": "Alice", "horse_name": "Thunder", "ranking": 1},
        {"participant_name": "Bob", "horse_name": "Storm", "ranking": 2},
    ])
    assert len(results) == 2
    assert results[0].participant_name == "Alice"
