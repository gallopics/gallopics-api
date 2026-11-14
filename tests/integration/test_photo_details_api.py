import pytest
from sqlalchemy import select

from app.models.enums import PhotographerStatus, PhotoTagType
from app.models.photographer import PhotoTag
from tests.integration.test_photo_prices_api import (
    DEFAULT_PRICES,
    URL,
    _other_photographers_photo,
    _prices,
    _seed_photo,
    _seed_photographer,
)


async def _tag(db_session, photo, tag_type, value):
    db_session.add(PhotoTag(photo_id=photo.id, type=tag_type, value=value))
    await db_session.flush()


async def _tags(db_session, photo):
    result = await db_session.execute(
        select(PhotoTag.type, PhotoTag.value).where(PhotoTag.photo_id == photo.id)
    )
    return {tag_type.value: value for tag_type, value in result.all()}


async def _matched_photo(db_session, photographer):
    """A photo as auto-matching leaves it: class, start number, rider and horse."""
    photo = await _seed_photo(db_session, photographer)
    for tag_type, value in [
        (PhotoTagType.CLASS, "1.20 m"),
        (PhotoTagType.START_NUMBER, "12"),
        (PhotoTagType.RIDER, "Old Rider"),
        (PhotoTagType.HORSE, "Old Horse"),
    ]:
        await _tag(db_session, photo, tag_type, value)
    return photo


async def test_sets_rider_and_horse_on_several_photos_and_keeps_other_tags(
    async_client, db_session, photographer_user, photographer_auth_headers
):
    photographer = await _seed_photographer(db_session, photographer_user)
    photos = [await _matched_photo(db_session, photographer) for _ in range(2)]

    response = await async_client.patch(
        URL,
        json={
            "photo_ids": [str(photo.id) for photo in photos],
            "rider": "  New Rider ",
            "horse": "New Horse",
        },
        headers=photographer_auth_headers,
    )

    assert response.status_code == 200, response.text
    expected = {"class": "1.20 m", "start_number": "12", "rider": "New Rider", "horse": "New Horse"}
    assert [item["id"] for item in response.json()] == [str(photo.id) for photo in photos]
    for item in response.json():
        assert {tag["type"]: tag["value"] for tag in item["tags"]} == expected
    for photo in photos:
        assert await _tags(db_session, photo) == expected


@pytest.mark.parametrize("removed", ["", None, "   "])
async def test_empty_rider_removes_it_and_a_left_out_horse_stays(
    async_client, db_session, photographer_user, photographer_auth_headers, removed
):
    photo = await _matched_photo(db_session, await _seed_photographer(db_session, photographer_user))

    response = await async_client.patch(
        URL, json={"photo_ids": [str(photo.id)], "rider": removed}, headers=photographer_auth_headers
    )

    assert response.status_code == 200, response.text
    assert await _tags(db_session, photo) == {
        "class": "1.20 m",
        "start_number": "12",
        "horse": "Old Horse",
    }


async def test_sets_prices_and_tags_together(
    async_client, db_session, photographer_user, photographer_auth_headers
):
    photo = await _matched_photo(db_session, await _seed_photographer(db_session, photographer_user))

    response = await async_client.patch(
        URL,
        json={"photo_ids": [str(photo.id)], "horse": "New Horse", "prices": {"web": 5900}},
        headers=photographer_auth_headers,
    )

    assert response.status_code == 200, response.text
    expected_prices = {**DEFAULT_PRICES, "web": 5900}
    assert response.json()[0]["prices"] == expected_prices
    assert await _prices(db_session, photo) == expected_prices
    assert (await _tags(db_session, photo))["horse"] == "New Horse"
    assert (await _tags(db_session, photo))["rider"] == "Old Rider"


async def test_another_photographers_photo_changes_nothing(
    async_client, db_session, photographer_user, photographer_auth_headers
):
    own = await _matched_photo(db_session, await _seed_photographer(db_session, photographer_user))
    other = await _other_photographers_photo(db_session)
    own_tags = await _tags(db_session, own)

    response = await async_client.patch(
        URL,
        json={"photo_ids": [str(own.id), str(other.id)], "rider": "New Rider", "prices": {"web": 5900}},
        headers=photographer_auth_headers,
    )

    assert response.status_code == 403
    assert await _tags(db_session, own) == own_tags
    assert await _tags(db_session, other) == {}
    assert await _prices(db_session, own) == DEFAULT_PRICES
    assert await _prices(db_session, other) == DEFAULT_PRICES


async def test_unknown_photo_is_not_found(
    async_client, db_session, photographer_user, photographer_auth_headers
):
    photo = await _matched_photo(db_session, await _seed_photographer(db_session, photographer_user))
    own_tags = await _tags(db_session, photo)

    response = await async_client.patch(
        URL,
        json={"photo_ids": [str(photo.id), "00000000-0000-0000-0000-000000000000"], "rider": "X"},
        headers=photographer_auth_headers,
    )

    assert response.status_code == 404
    assert await _tags(db_session, photo) == own_tags


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"prices": {}},
        {"prices": None},
        {"prices": {"web": 4800}},  # under the minimum
    ],
)
async def test_rejects_requests_without_a_valid_change(
    async_client, db_session, photographer_user, photographer_auth_headers, body
):
    photo = await _matched_photo(db_session, await _seed_photographer(db_session, photographer_user))

    response = await async_client.patch(
        URL, json={"photo_ids": [str(photo.id)], **body}, headers=photographer_auth_headers
    )

    assert response.status_code == 422


@pytest.mark.parametrize("photo_ids", [[], "duplicate"])
async def test_rejects_empty_or_duplicate_photo_ids(
    async_client, db_session, photographer_user, photographer_auth_headers, photo_ids
):
    photo = await _seed_photo(db_session, await _seed_photographer(db_session, photographer_user))
    if photo_ids == "duplicate":
        photo_ids = [str(photo.id), str(photo.id)]

    response = await async_client.patch(
        URL, json={"photo_ids": photo_ids, "rider": "X"}, headers=photographer_auth_headers
    )

    assert response.status_code == 422
    assert await _tags(db_session, photo) == {}


@pytest.mark.parametrize("status", [PhotographerStatus.PENDING, PhotographerStatus.SUSPENDED])
async def test_unapproved_photographer_cannot_update(
    async_client, db_session, photographer_user, photographer_auth_headers, status
):
    photo = await _seed_photo(db_session, await _seed_photographer(db_session, photographer_user, status))

    response = await async_client.patch(
        URL, json={"photo_ids": [str(photo.id)], "rider": "X"}, headers=photographer_auth_headers
    )

    assert response.status_code == 403
    assert await _tags(db_session, photo) == {}


async def test_buyer_cannot_update(async_client, db_session, auth_headers):
    photo = await _other_photographers_photo(db_session)

    response = await async_client.patch(
        URL, json={"photo_ids": [str(photo.id)], "rider": "X"}, headers=auth_headers
    )

    assert response.status_code == 403
    assert await _tags(db_session, photo) == {}
