import pytest
from sqlalchemy import select

from app.models.enums import PhotographerStatus, PhotoStatus, PhotoVisibility, UserRole
from app.models.event import Event
from app.models.photographer import Photo, Photographer
from app.models.user import User
from tests.factories import make_event

DEFAULT_PRICES = {"web": 49900, "high": 99900, "commercial": 150000}


async def _seed_photographer(db_session, user, status=PhotographerStatus.APPROVED):
    photographer = Photographer(
        user_id=user.id,
        slug=f"pricing-{user.clerk_user_id}",
        display_name="Pricing Photographer",
        status=status,
    )
    db_session.add(photographer)
    await db_session.flush()
    return photographer


async def _seed_photo(db_session, photographer):
    event = Event(**make_event(name="Pricing Event"))
    db_session.add(event)
    await db_session.flush()
    photo = Photo(
        event_id=event.id,
        photographer_id=photographer.id,
        storage_key_original="originals/photo.jpg",
        price=10000,
        status=PhotoStatus.READY,
        visibility=PhotoVisibility.PUBLISHED,
    )
    db_session.add(photo)
    await db_session.flush()
    return photo


async def _other_photographers_photo(db_session):
    user = User(clerk_user_id="clerk_other_pg", email="other-pg@example.com", role=UserRole.PHOTOGRAPHER)
    db_session.add(user)
    await db_session.flush()
    return await _seed_photo(db_session, await _seed_photographer(db_session, user))


async def _prices(db_session, photo):
    result = await db_session.execute(
        select(Photo).where(Photo.id == photo.id).execution_options(populate_existing=True)
    )
    return result.scalar_one().prices


async def test_photos_start_with_default_prices(async_client, db_session, photographer_user):
    photo = await _seed_photo(db_session, await _seed_photographer(db_session, photographer_user))

    response = await async_client.get(f"/api/v1/photos/{photo.id}")

    assert response.status_code == 200
    assert response.json()["prices"] == DEFAULT_PRICES


async def test_owner_sets_one_photos_prices(
    async_client, db_session, photographer_user, photographer_auth_headers
):
    photo = await _seed_photo(db_session, await _seed_photographer(db_session, photographer_user))

    response = await async_client.patch(
        f"/api/v1/photographer/photos/{photo.id}",
        json={"prices": {"web": 5900, "commercial": 250000}},
        headers=photographer_auth_headers,
    )

    assert response.status_code == 200, response.text
    # A tier left out keeps its price
    expected = {"web": 5900, "high": 99900, "commercial": 250000}
    assert response.json()["prices"] == expected
    assert await _prices(db_session, photo) == expected


async def test_owner_sets_prices_for_several_photos(
    async_client, db_session, photographer_user, photographer_auth_headers
):
    photographer = await _seed_photographer(db_session, photographer_user)
    photos = [await _seed_photo(db_session, photographer) for _ in range(2)]
    prices = {"web": 4900, "high": 79900, "commercial": 120000}

    response = await async_client.patch(
        "/api/v1/photographer/photos/prices",
        json={"photo_ids": [str(photo.id) for photo in photos], "prices": prices},
        headers=photographer_auth_headers,
    )

    assert response.status_code == 200, response.text
    assert [item["prices"] for item in response.json()] == [prices, prices]
    for photo in photos:
        assert await _prices(db_session, photo) == prices


async def test_cannot_set_another_photographers_prices(
    async_client, db_session, photographer_user, photographer_auth_headers
):
    await _seed_photographer(db_session, photographer_user)
    photo = await _other_photographers_photo(db_session)

    response = await async_client.patch(
        f"/api/v1/photographer/photos/{photo.id}",
        json={"prices": {"web": 5900}},
        headers=photographer_auth_headers,
    )

    assert response.status_code == 403
    assert await _prices(db_session, photo) == DEFAULT_PRICES


async def test_bulk_update_with_another_photographers_photo_changes_nothing(
    async_client, db_session, photographer_user, photographer_auth_headers
):
    own = await _seed_photo(db_session, await _seed_photographer(db_session, photographer_user))
    other = await _other_photographers_photo(db_session)

    response = await async_client.patch(
        "/api/v1/photographer/photos/prices",
        json={"photo_ids": [str(own.id), str(other.id)], "prices": {"web": 5900}},
        headers=photographer_auth_headers,
    )

    assert response.status_code == 403
    assert await _prices(db_session, own) == DEFAULT_PRICES
    assert await _prices(db_session, other) == DEFAULT_PRICES


async def test_bulk_update_with_unknown_photo_is_not_found(
    async_client, db_session, photographer_user, photographer_auth_headers
):
    photo = await _seed_photo(db_session, await _seed_photographer(db_session, photographer_user))

    response = await async_client.patch(
        "/api/v1/photographer/photos/prices",
        json={
            "photo_ids": [str(photo.id), "00000000-0000-0000-0000-000000000000"],
            "prices": {"web": 5900},
        },
        headers=photographer_auth_headers,
    )

    assert response.status_code == 404
    assert await _prices(db_session, photo) == DEFAULT_PRICES


@pytest.mark.parametrize("status", [PhotographerStatus.PENDING, PhotographerStatus.SUSPENDED])
async def test_unapproved_photographer_cannot_set_prices(
    async_client, db_session, photographer_user, photographer_auth_headers, status
):
    photo = await _seed_photo(db_session, await _seed_photographer(db_session, photographer_user, status))

    single = await async_client.patch(
        f"/api/v1/photographer/photos/{photo.id}",
        json={"prices": {"web": 5900}},
        headers=photographer_auth_headers,
    )
    bulk = await async_client.patch(
        "/api/v1/photographer/photos/prices",
        json={"photo_ids": [str(photo.id)], "prices": {"web": 5900}},
        headers=photographer_auth_headers,
    )

    assert single.status_code == 403
    assert bulk.status_code == 403
    assert await _prices(db_session, photo) == DEFAULT_PRICES


async def test_buyer_cannot_set_prices(async_client, db_session, auth_headers):
    photo = await _other_photographers_photo(db_session)

    response = await async_client.patch(
        "/api/v1/photographer/photos/prices",
        json={"photo_ids": [str(photo.id)], "prices": {"web": 5900}},
        headers=auth_headers,
    )

    assert response.status_code == 403
    assert await _prices(db_session, photo) == DEFAULT_PRICES


@pytest.mark.parametrize(
    "amount",
    [
        4800,  # 48 SEK, under the minimum
        4950,  # 49.50 SEK, not whole SEK
        0,
        -10000,
        1_000_100,  # 10 001 SEK, over the maximum
        "lots",
    ],
)
async def test_rejects_invalid_prices(
    async_client, db_session, photographer_user, photographer_auth_headers, amount
):
    photo = await _seed_photo(db_session, await _seed_photographer(db_session, photographer_user))

    single = await async_client.patch(
        f"/api/v1/photographer/photos/{photo.id}",
        json={"prices": {"high": amount}},
        headers=photographer_auth_headers,
    )
    bulk = await async_client.patch(
        "/api/v1/photographer/photos/prices",
        json={"photo_ids": [str(photo.id)], "prices": {"web": 5900, "high": amount}},
        headers=photographer_auth_headers,
    )

    assert single.status_code == 422
    assert bulk.status_code == 422
    assert await _prices(db_session, photo) == DEFAULT_PRICES


@pytest.mark.parametrize("amount", [4900, 1_000_000])
async def test_accepts_prices_at_the_limits(
    async_client, db_session, photographer_user, photographer_auth_headers, amount
):
    photo = await _seed_photo(db_session, await _seed_photographer(db_session, photographer_user))

    response = await async_client.patch(
        f"/api/v1/photographer/photos/{photo.id}",
        json={"prices": {"web": amount, "high": amount, "commercial": amount}},
        headers=photographer_auth_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["prices"] == {"web": amount, "high": amount, "commercial": amount}
