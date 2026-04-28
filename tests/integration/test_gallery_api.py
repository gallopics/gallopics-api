import uuid

from app.models.enums import (
    PhotographerStatus,
    PhotoStatus,
    PhotoTagType,
    PhotoVisibility,
    UserRole,
)
from app.models.event import Event
from app.models.photographer import Photo, Photographer, PhotoTag
from app.models.user import User
from tests.factories import make_event


async def _seed_gallery(db_session):
    """Create user, photographer, event, and some photos for gallery tests."""
    user = User(clerk_user_id="clerk_gallery_user", email="gallery@test.com", role=UserRole.PHOTOGRAPHER)
    db_session.add(user)
    await db_session.flush()

    photographer = Photographer(
        user_id=user.id,
        slug="test-photographer",
        display_name="Test Photographer",
        status=PhotographerStatus.APPROVED,
    )
    db_session.add(photographer)
    await db_session.flush()

    event = Event(**make_event(name="Gallery Event"))
    db_session.add(event)
    await db_session.flush()

    # Published + Ready photo
    p1 = Photo(
        event_id=event.id, photographer_id=photographer.id,
        storage_key_original="originals/photo1.jpg",
        storage_key_preview="previews/photo1.jpg",
        storage_key_thumbnail="thumbnails/photo1.jpg",
        price=10000, status=PhotoStatus.READY, visibility=PhotoVisibility.PUBLISHED,
    )
    # Draft photo (should not appear in gallery)
    p2 = Photo(
        event_id=event.id, photographer_id=photographer.id,
        storage_key_original="originals/photo2.jpg",
        price=10000, status=PhotoStatus.READY, visibility=PhotoVisibility.DRAFT,
    )
    # Processing photo (should not appear)
    p3 = Photo(
        event_id=event.id, photographer_id=photographer.id,
        storage_key_original="originals/photo3.jpg",
        price=10000, status=PhotoStatus.PROCESSING, visibility=PhotoVisibility.PUBLISHED,
    )
    db_session.add_all([p1, p2, p3])
    await db_session.flush()

    # Add tags to p1
    tag1 = PhotoTag(photo_id=p1.id, type=PhotoTagType.RIDER, value="Anna Svensson")
    tag2 = PhotoTag(photo_id=p1.id, type=PhotoTagType.HORSE, value="Thunder")
    db_session.add_all([tag1, tag2])
    await db_session.flush()

    return event, p1, p2, p3


async def test_gallery_returns_only_published_and_ready(async_client, db_session):
    event, p1, p2, p3 = await _seed_gallery(db_session)
    response = await async_client.get(f"/api/v1/events/{event.id}/gallery")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == str(p1.id)


async def test_gallery_empty_event(async_client, db_session):
    event = Event(**make_event(name="Empty Gallery Event"))
    db_session.add(event)
    await db_session.flush()

    response = await async_client.get(f"/api/v1/events/{event.id}/gallery")
    assert response.status_code == 200
    assert response.json()["total"] == 0


async def test_gallery_pagination(async_client, db_session):
    event, p1, _, _ = await _seed_gallery(db_session)
    response = await async_client.get(f"/api/v1/events/{event.id}/gallery?page=1&page_size=10")
    assert response.status_code == 200


async def test_search_by_rider(async_client, db_session):
    event, _, _, _ = await _seed_gallery(db_session)
    response = await async_client.get(f"/api/v1/events/{event.id}/gallery/search?q=Anna")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1


async def test_search_by_horse(async_client, db_session):
    event, _, _, _ = await _seed_gallery(db_session)
    response = await async_client.get(f"/api/v1/events/{event.id}/gallery/search?q=Thunder")
    assert response.status_code == 200
    assert len(response.json()) == 1


async def test_search_no_results(async_client, db_session):
    event, _, _, _ = await _seed_gallery(db_session)
    response = await async_client.get(f"/api/v1/events/{event.id}/gallery/search?q=Nonexistent")
    assert response.status_code == 200
    assert response.json() == []


async def test_photo_detail(async_client, db_session):
    event, p1, _, _ = await _seed_gallery(db_session)
    response = await async_client.get(f"/api/v1/photos/{p1.id}")
    assert response.status_code == 200
    assert response.json()["id"] == str(p1.id)


async def test_photo_detail_draft_not_accessible(async_client, db_session):
    event, _, p2, _ = await _seed_gallery(db_session)
    response = await async_client.get(f"/api/v1/photos/{p2.id}")
    assert response.status_code == 404


async def test_photo_detail_not_found(async_client):
    response = await async_client.get(f"/api/v1/photos/{uuid.uuid4()}")
    assert response.status_code == 404
