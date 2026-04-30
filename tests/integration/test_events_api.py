import uuid
from datetime import date

import httpx
import respx

from app.models.event import Event, EventResult
from tests.factories import make_event


async def _seed_event(db_session, **overrides) -> Event:
    data = make_event(**overrides)
    event = Event(**data)
    db_session.add(event)
    await db_session.flush()
    return event


async def test_list_events_empty(async_client):
    response = await async_client.get("/api/v1/events")
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0


async def test_list_events_with_data(async_client, db_session):
    for i in range(3):
        await _seed_event(db_session, name=f"Event {i}")
    response = await async_client.get("/api/v1/events")
    assert response.status_code == 200
    assert response.json()["total"] == 3


async def test_list_events_pagination(async_client, db_session):
    for i in range(25):
        await _seed_event(db_session, start_date=date(2026, 1, i + 1))
    response = await async_client.get("/api/v1/events?page=2&page_size=10")
    data = response.json()
    assert data["total"] == 25
    assert len(data["items"]) == 10
    assert data["page"] == 2


async def test_list_events_filter_discipline(async_client, db_session):
    await _seed_event(db_session, discipline="dressage")
    await _seed_event(db_session, discipline="jumping")
    response = await async_client.get("/api/v1/events?discipline=dressage")
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["discipline"] == "dressage"


async def test_list_events_filter_date_range(async_client, db_session):
    await _seed_event(db_session, start_date=date(2026, 1, 10))
    await _seed_event(db_session, start_date=date(2026, 6, 15))
    await _seed_event(db_session, start_date=date(2026, 12, 1))
    response = await async_client.get("/api/v1/events?date_from=2026-06-01&date_to=2026-06-30")
    assert response.json()["total"] == 1


async def test_list_events_filter_search(async_client, db_session):
    await _seed_event(db_session, name="Stockholm Grand Prix")
    await _seed_event(db_session, name="Malmö Open")
    response = await async_client.get("/api/v1/events?search=Stockholm")
    assert response.json()["total"] == 1


async def test_get_event_by_id(async_client, db_session):
    event = await _seed_event(db_session, name="Specific Event")
    response = await async_client.get(f"/api/v1/events/{event.id}")
    assert response.status_code == 200
    assert response.json()["name"] == "Specific Event"


async def test_get_event_not_found(async_client):
    response = await async_client.get(f"/api/v1/events/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_get_event_results(async_client, db_session):
    event = await _seed_event(db_session)
    result = EventResult(
        event_id=event.id, participant_name="Alice", horse_name="Thunder", ranking=1
    )
    db_session.add(result)
    await db_session.flush()

    response = await async_client.get(f"/api/v1/events/{event.id}/results")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["participant_name"] == "Alice"


async def test_get_event_results_empty(async_client, db_session):
    event = await _seed_event(db_session)
    response = await async_client.get(f"/api/v1/events/{event.id}/results")
    assert response.status_code == 200
    assert response.json() == []


@respx.mock
async def test_get_event_schedule(async_client, db_session):
    event = await _seed_event(
        db_session,
        equipe_id="89761",
        raw_equipe_payload={"id": 78337, "equipe_id": 89761},
    )
    respx.get("https://online.equipe.com/api/v1/meetings/78337/schedule").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 78337,
                "discipline": "dressage",
                "meeting_classes": [
                    {
                        "id": 1198540,
                        "name": "Prix St-Georges · CDI1*",
                        "start_at": "2026-05-07 15:00:00 +0200",
                        "display_time": "15:00",
                        "discipline": "dressage",
                        "arena": "Green arena",
                        "position": 0,
                        "date": "2026-05-07",
                        "class_no": "D09",
                    },
                    {
                        "id": 1190641,
                        "name": "Masterlist",
                        "discipline": "list",
                        "excluded_from_total": True,
                        "date": "2026-05-06",
                    },
                ],
            },
        )
    )

    response = await async_client.get(f"/api/v1/events/{event.id}/schedule")

    assert response.status_code == 200
    data = response.json()
    assert data["event_id"] == str(event.id)
    assert data["equipe_meeting_id"] == "78337"
    assert data["classes_count"] == 1
    assert data["days"][0]["date"] == "2026-05-07"
    assert data["days"][0]["classes"][0]["name"] == "D09 · Prix St-Georges · CDI1*"
    assert data["days"][0]["classes"][0]["arena"] == "Green arena"
