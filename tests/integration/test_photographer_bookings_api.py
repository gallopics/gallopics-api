from app.models.enums import PhotographerStatus
from app.models.event import Event
from app.models.photographer import Photographer
from tests.factories import make_event


async def _seed_photographer(db_session, photographer_user):
    photographer = Photographer(
        user_id=photographer_user.id,
        slug="booking-photographer",
        display_name="Booking Photographer",
        status=PhotographerStatus.APPROVED,
    )
    db_session.add(photographer)
    await db_session.flush()
    return photographer


async def _seed_event(db_session, **overrides):
    event = Event(**make_event(**overrides))
    db_session.add(event)
    await db_session.flush()
    return event


async def test_book_event(async_client, db_session, photographer_user, photographer_auth_headers):
    await _seed_photographer(db_session, photographer_user)
    event = await _seed_event(db_session, name="Bookable Event")

    response = await async_client.post(
        f"/api/v1/photographer/bookings/{event.id}",
        headers=photographer_auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["id"] == str(event.id)

    list_response = await async_client.get(
        "/api/v1/photographer/bookings",
        headers=photographer_auth_headers,
    )
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [str(event.id)]


async def test_cancel_event_booking(async_client, db_session, photographer_user, photographer_auth_headers):
    await _seed_photographer(db_session, photographer_user)
    event = await _seed_event(db_session, name="Cancelable Event")
    await async_client.post(
        f"/api/v1/photographer/bookings/{event.id}",
        headers=photographer_auth_headers,
    )

    response = await async_client.delete(
        f"/api/v1/photographer/bookings/{event.id}",
        headers=photographer_auth_headers,
    )

    assert response.status_code == 204

    list_response = await async_client.get(
        "/api/v1/photographer/bookings",
        headers=photographer_auth_headers,
    )
    assert list_response.status_code == 200
    assert list_response.json() == []
