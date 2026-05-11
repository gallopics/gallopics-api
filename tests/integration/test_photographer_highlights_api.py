from app.models.enums import PhotographerStatus, UserRole
from app.models.event import Event
from app.models.photographer import Photo, Photographer
from app.models.user import User
from tests.factories import make_event


async def _seed_photographer(db_session, photographer_user, slug="highlight-photographer"):
    photographer = Photographer(
        user_id=photographer_user.id,
        slug=slug,
        display_name="Highlight Photographer",
        status=PhotographerStatus.APPROVED,
    )
    db_session.add(photographer)
    await db_session.flush()
    return photographer


async def _seed_photo(db_session, photographer):
    event = Event(**make_event(name="Highlight Event"))
    db_session.add(event)
    await db_session.flush()

    photo = Photo(
        event_id=event.id,
        photographer_id=photographer.id,
        storage_key_original="originals/highlight.jpg",
        price=10000,
    )
    db_session.add(photo)
    await db_session.flush()
    return photo


async def test_highlights_round_trip_for_current_photographer(
    async_client,
    db_session,
    photographer_user,
    photographer_auth_headers,
):
    photographer = await _seed_photographer(db_session, photographer_user)
    photo = await _seed_photo(db_session, photographer)

    update_response = await async_client.put(
        "/api/v1/photographer/highlights",
        headers=photographer_auth_headers,
        json={"photo_ids": [str(photo.id)]},
    )

    assert update_response.status_code == 200
    assert update_response.json() == {"highlights": [str(photo.id)]}

    get_response = await async_client.get(
        "/api/v1/photographer/highlights",
        headers=photographer_auth_headers,
    )

    assert get_response.status_code == 200
    assert get_response.json() == {"highlights": [str(photo.id)]}


async def test_public_photographer_profile_includes_highlights(
    async_client,
    db_session,
    photographer_user,
):
    photographer = await _seed_photographer(db_session, photographer_user)
    photo = await _seed_photo(db_session, photographer)
    photographer.highlights = [str(photo.id)]
    await db_session.flush()

    response = await async_client.get(f"/api/v1/photographers/{photographer.slug}")

    assert response.status_code == 200
    assert response.json()["highlights"] == [str(photo.id)]


async def test_update_highlights_rejects_other_photographers_photo(
    async_client,
    db_session,
    photographer_user,
    photographer_auth_headers,
):
    await _seed_photographer(db_session, photographer_user)
    other_user = User(
        clerk_user_id="clerk_other_photographer_test",
        email="other-photo@example.com",
        role=UserRole.PHOTOGRAPHER,
    )
    db_session.add(other_user)
    await db_session.flush()
    other_photographer = await _seed_photographer(
        db_session,
        other_user,
        slug="other-highlight-photographer",
    )
    other_photo = await _seed_photo(db_session, other_photographer)

    response = await async_client.put(
        "/api/v1/photographer/highlights",
        headers=photographer_auth_headers,
        json={"photo_ids": [str(other_photo.id)]},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "One or more highlight photos do not belong to this photographer"
