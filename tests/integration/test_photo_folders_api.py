from sqlalchemy import select

from app.models.enums import PhotographerStatus, PhotoStatus, PhotoVisibility, UserRole
from app.models.event import Event
from app.models.photographer import Photo, PhotoFolder, Photographer
from app.models.user import User
from tests.factories import make_event


async def _seed_photographer(db_session, user, status=PhotographerStatus.APPROVED):
    photographer = Photographer(
        user_id=user.id,
        slug=f"folders-{user.clerk_user_id}",
        display_name="Folders Photographer",
        status=status,
    )
    db_session.add(photographer)
    await db_session.flush()
    return photographer


async def _seed_event(db_session, name="Folders Event"):
    event = Event(**make_event(name=name))
    db_session.add(event)
    await db_session.flush()
    return event


async def _seed_photo(db_session, photographer, event, folder=None):
    photo = Photo(
        event_id=event.id,
        photographer_id=photographer.id,
        storage_key_original="originals/photo.jpg",
        storage_key_preview="previews/photo.jpg",
        price=10000,
        status=PhotoStatus.READY,
        visibility=PhotoVisibility.PUBLISHED,
        folder_id=folder.id if folder else None,
    )
    db_session.add(photo)
    await db_session.flush()
    return photo


async def _seed_folder(db_session, photographer, event, name="Jumping"):
    folder = PhotoFolder(photographer_id=photographer.id, event_id=event.id, name=name)
    db_session.add(folder)
    await db_session.flush()
    return folder


async def _other_photographer(db_session):
    user = User(clerk_user_id="clerk_other_pg", email="other-pg@example.com", role=UserRole.PHOTOGRAPHER)
    db_session.add(user)
    await db_session.flush()
    return await _seed_photographer(db_session, user)


async def _folder_id(db_session, photo):
    result = await db_session.execute(
        select(Photo).where(Photo.id == photo.id).execution_options(populate_existing=True)
    )
    return result.scalar_one().folder_id


async def test_owner_creates_lists_and_renames_folders(
    async_client, db_session, photographer_user, photographer_auth_headers
):
    photographer = await _seed_photographer(db_session, photographer_user)
    event = await _seed_event(db_session)
    other_event = await _seed_event(db_session, name="Other Event")
    await _seed_folder(db_session, photographer, other_event, name="Elsewhere")

    created = await async_client.post(
        "/api/v1/photographer/folders",
        json={"event_id": str(event.id), "name": "  Warm-up  "},
        headers=photographer_auth_headers,
    )
    assert created.status_code == 200, created.text
    folder = created.json()
    assert folder["name"] == "Warm-up"
    assert folder["event_id"] == str(event.id)

    listed = await async_client.get(
        f"/api/v1/photographer/folders?event_id={event.id}", headers=photographer_auth_headers
    )
    assert listed.status_code == 200
    assert [item["name"] for item in listed.json()] == ["Warm-up"]

    renamed = await async_client.patch(
        f"/api/v1/photographer/folders/{folder['id']}",
        json={"name": "Prize giving"},
        headers=photographer_auth_headers,
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Prize giving"


async def test_folder_names_are_unique_per_event_and_uncategorised_is_reserved(
    async_client, db_session, photographer_user, photographer_auth_headers
):
    photographer = await _seed_photographer(db_session, photographer_user)
    event = await _seed_event(db_session)
    other_event = await _seed_event(db_session, name="Other Event")
    await _seed_folder(db_session, photographer, event, name="Jumping")
    url = "/api/v1/photographer/folders"

    duplicate = await async_client.post(
        url, json={"event_id": str(event.id), "name": "jumping"}, headers=photographer_auth_headers
    )
    reserved = await async_client.post(
        url, json={"event_id": str(event.id), "name": "Uncategorised"}, headers=photographer_auth_headers
    )
    empty = await async_client.post(
        url, json={"event_id": str(event.id), "name": "   "}, headers=photographer_auth_headers
    )
    same_name_other_event = await async_client.post(
        url, json={"event_id": str(other_event.id), "name": "Jumping"}, headers=photographer_auth_headers
    )

    assert duplicate.status_code == 409
    assert reserved.status_code == 422
    assert empty.status_code == 422
    assert same_name_other_event.status_code == 200


async def test_owner_moves_one_photo_into_a_folder_and_back(
    async_client, db_session, photographer_user, photographer_auth_headers
):
    photographer = await _seed_photographer(db_session, photographer_user)
    event = await _seed_event(db_session)
    folder = await _seed_folder(db_session, photographer, event)
    photo = await _seed_photo(db_session, photographer, event)

    moved = await async_client.patch(
        "/api/v1/photographer/photos/folder",
        json={"photo_ids": [str(photo.id)], "folder_id": str(folder.id)},
        headers=photographer_auth_headers,
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()[0]["folder_id"] == str(folder.id)
    assert await _folder_id(db_session, photo) == folder.id

    # Undo: back to Uncategorised
    back = await async_client.patch(
        "/api/v1/photographer/photos/folder",
        json={"photo_ids": [str(photo.id)], "folder_id": None},
        headers=photographer_auth_headers,
    )
    assert back.status_code == 200, back.text
    assert back.json()[0]["folder_id"] is None
    assert await _folder_id(db_session, photo) is None


async def test_owner_moves_several_photos_at_once(
    async_client, db_session, photographer_user, photographer_auth_headers
):
    photographer = await _seed_photographer(db_session, photographer_user)
    event = await _seed_event(db_session)
    folder = await _seed_folder(db_session, photographer, event)
    photos = [await _seed_photo(db_session, photographer, event) for _ in range(3)]

    response = await async_client.patch(
        "/api/v1/photographer/photos/folder",
        json={"photo_ids": [str(photo.id) for photo in photos], "folder_id": str(folder.id)},
        headers=photographer_auth_headers,
    )

    assert response.status_code == 200, response.text
    assert [item["folder_id"] for item in response.json()] == [str(folder.id)] * 3
    for photo in photos:
        assert await _folder_id(db_session, photo) == folder.id


async def test_deleting_a_folder_moves_its_photos_to_uncategorised(
    async_client, db_session, photographer_user, photographer_auth_headers
):
    photographer = await _seed_photographer(db_session, photographer_user)
    event = await _seed_event(db_session)
    folder = await _seed_folder(db_session, photographer, event)
    kept = await _seed_folder(db_session, photographer, event, name="Kept")
    photos = [await _seed_photo(db_session, photographer, event, folder) for _ in range(2)]
    other_photo = await _seed_photo(db_session, photographer, event, kept)

    response = await async_client.delete(
        f"/api/v1/photographer/folders/{folder.id}", headers=photographer_auth_headers
    )

    assert response.status_code == 204
    assert await db_session.get(PhotoFolder, folder.id) is None
    for photo in photos:
        assert await _folder_id(db_session, photo) is None
        # The photos themselves stay
        assert await db_session.get(Photo, photo.id) is not None
    assert await _folder_id(db_session, other_photo) == kept.id


async def test_cannot_use_another_photographers_folder(
    async_client, db_session, photographer_user, photographer_auth_headers
):
    photographer = await _seed_photographer(db_session, photographer_user)
    event = await _seed_event(db_session)
    other_folder = await _seed_folder(db_session, await _other_photographer(db_session), event)
    photo = await _seed_photo(db_session, photographer, event)

    move = await async_client.patch(
        "/api/v1/photographer/photos/folder",
        json={"photo_ids": [str(photo.id)], "folder_id": str(other_folder.id)},
        headers=photographer_auth_headers,
    )
    rename = await async_client.patch(
        f"/api/v1/photographer/folders/{other_folder.id}",
        json={"name": "Mine now"},
        headers=photographer_auth_headers,
    )
    delete = await async_client.delete(
        f"/api/v1/photographer/folders/{other_folder.id}", headers=photographer_auth_headers
    )
    listed = await async_client.get("/api/v1/photographer/folders", headers=photographer_auth_headers)

    assert move.status_code == 404
    assert rename.status_code == 404
    assert delete.status_code == 404
    assert listed.json() == []
    assert await _folder_id(db_session, photo) is None
    assert await db_session.get(PhotoFolder, other_folder.id) is not None


async def test_bulk_move_with_another_photographers_photo_moves_nothing(
    async_client, db_session, photographer_user, photographer_auth_headers
):
    photographer = await _seed_photographer(db_session, photographer_user)
    event = await _seed_event(db_session)
    folder = await _seed_folder(db_session, photographer, event)
    own = await _seed_photo(db_session, photographer, event)
    other = await _seed_photo(db_session, await _other_photographer(db_session), event)

    response = await async_client.patch(
        "/api/v1/photographer/photos/folder",
        json={"photo_ids": [str(own.id), str(other.id)], "folder_id": str(folder.id)},
        headers=photographer_auth_headers,
    )

    assert response.status_code == 403
    assert await _folder_id(db_session, own) is None
    assert await _folder_id(db_session, other) is None


async def test_cannot_move_a_photo_into_another_events_folder(
    async_client, db_session, photographer_user, photographer_auth_headers
):
    photographer = await _seed_photographer(db_session, photographer_user)
    folder = await _seed_folder(db_session, photographer, await _seed_event(db_session))
    photo = await _seed_photo(db_session, photographer, await _seed_event(db_session, name="Other Event"))

    response = await async_client.patch(
        "/api/v1/photographer/photos/folder",
        json={"photo_ids": [str(photo.id)], "folder_id": str(folder.id)},
        headers=photographer_auth_headers,
    )

    assert response.status_code == 400
    assert await _folder_id(db_session, photo) is None


async def test_pending_photographer_cannot_manage_folders(
    async_client, db_session, photographer_user, photographer_auth_headers
):
    photographer = await _seed_photographer(db_session, photographer_user, status=PhotographerStatus.PENDING)
    event = await _seed_event(db_session)
    folder = await _seed_folder(db_session, photographer, event)
    photo = await _seed_photo(db_session, photographer, event)

    create = await async_client.post(
        "/api/v1/photographer/folders",
        json={"event_id": str(event.id), "name": "New"},
        headers=photographer_auth_headers,
    )
    move = await async_client.patch(
        "/api/v1/photographer/photos/folder",
        json={"photo_ids": [str(photo.id)], "folder_id": str(folder.id)},
        headers=photographer_auth_headers,
    )
    delete = await async_client.delete(
        f"/api/v1/photographer/folders/{folder.id}", headers=photographer_auth_headers
    )

    assert create.status_code == 403
    assert move.status_code == 403
    assert delete.status_code == 403


async def test_buyers_cannot_manage_folders(async_client, db_session, auth_headers):
    user = User(clerk_user_id="clerk_user_test", email="test@example.com", role=UserRole.USER)
    db_session.add(user)
    await db_session.flush()

    response = await async_client.get("/api/v1/photographer/folders", headers=auth_headers)

    assert response.status_code == 403


async def test_folders_stay_private_on_public_photo_responses(
    async_client, db_session, photographer_user, photographer_auth_headers
):
    photographer = await _seed_photographer(db_session, photographer_user)
    event = await _seed_event(db_session)
    folder = await _seed_folder(db_session, photographer, event)
    photo = await _seed_photo(db_session, photographer, event, folder)

    public = await async_client.get(f"/api/v1/photos/{photo.id}")
    gallery = await async_client.get(f"/api/v1/events/{event.id}/gallery")
    own = await async_client.get(
        f"/api/v1/photographer/photos?event_id={event.id}", headers=photographer_auth_headers
    )

    assert public.status_code == 200
    assert "folder_id" not in public.json()
    assert gallery.status_code == 200
    assert gallery.json()["items"]
    assert all("folder_id" not in item for item in gallery.json()["items"])
    assert own.json()["items"][0]["folder_id"] == str(folder.id)


async def test_rename_checks_names_and_allows_a_case_change(
    async_client, db_session, photographer_user, photographer_auth_headers
):
    photographer = await _seed_photographer(db_session, photographer_user)
    event = await _seed_event(db_session)
    folder = await _seed_folder(db_session, photographer, event, name="Östra")
    await _seed_folder(db_session, photographer, event, name="Warm-up")
    url = f"/api/v1/photographer/folders/{folder.id}"

    taken = await async_client.patch(url, json={"name": "WARM-UP"}, headers=photographer_auth_headers)
    reserved = await async_client.patch(url, json={"name": "uncategorised"}, headers=photographer_auth_headers)
    case_change = await async_client.patch(url, json={"name": "ÖSTRA"}, headers=photographer_auth_headers)

    assert taken.status_code == 409
    assert reserved.status_code == 422
    assert case_change.status_code == 200, case_change.text
    assert case_change.json()["name"] == "ÖSTRA"


async def test_swedish_letters_count_as_the_same_name_in_any_case(
    async_client, db_session, photographer_user, photographer_auth_headers
):
    photographer = await _seed_photographer(db_session, photographer_user)
    event = await _seed_event(db_session)
    await _seed_folder(db_session, photographer, event, name="Östra ängen")

    response = await async_client.post(
        "/api/v1/photographer/folders",
        json={"event_id": str(event.id), "name": "ÖSTRA ÄNGEN"},
        headers=photographer_auth_headers,
    )

    assert response.status_code == 409


async def test_folders_are_listed_by_name(
    async_client, db_session, photographer_user, photographer_auth_headers
):
    photographer = await _seed_photographer(db_session, photographer_user)
    event = await _seed_event(db_session)
    for name in ["warm-up", "Arena B", "arena a"]:
        await _seed_folder(db_session, photographer, event, name=name)

    response = await async_client.get(
        f"/api/v1/photographer/folders?event_id={event.id}", headers=photographer_auth_headers
    )

    assert [item["name"] for item in response.json()] == ["arena a", "Arena B", "warm-up"]


async def test_unknown_event_folder_or_photo_is_not_found(
    async_client, db_session, photographer_user, photographer_auth_headers
):
    photographer = await _seed_photographer(db_session, photographer_user)
    event = await _seed_event(db_session)
    folder = await _seed_folder(db_session, photographer, event)
    photo = await _seed_photo(db_session, photographer, event)
    unknown = "00000000-0000-4000-8000-000000000000"

    no_event = await async_client.post(
        "/api/v1/photographer/folders",
        json={"event_id": unknown, "name": "New"},
        headers=photographer_auth_headers,
    )
    no_folder = await async_client.patch(
        "/api/v1/photographer/photos/folder",
        json={"photo_ids": [str(photo.id)], "folder_id": unknown},
        headers=photographer_auth_headers,
    )
    no_photo = await async_client.patch(
        "/api/v1/photographer/photos/folder",
        json={"photo_ids": [str(photo.id), unknown], "folder_id": str(folder.id)},
        headers=photographer_auth_headers,
    )
    delete_unknown = await async_client.delete(
        f"/api/v1/photographer/folders/{unknown}", headers=photographer_auth_headers
    )

    assert no_event.status_code == 404
    assert no_folder.status_code == 404
    assert no_photo.status_code == 404
    assert delete_unknown.status_code == 404
    assert await _folder_id(db_session, photo) is None


async def test_move_needs_an_explicit_folder_id(
    async_client, db_session, photographer_user, photographer_auth_headers
):
    photographer = await _seed_photographer(db_session, photographer_user)
    event = await _seed_event(db_session)
    folder = await _seed_folder(db_session, photographer, event)
    photo = await _seed_photo(db_session, photographer, event, folder)

    response = await async_client.patch(
        "/api/v1/photographer/photos/folder",
        json={"photo_ids": [str(photo.id)]},
        headers=photographer_auth_headers,
    )

    assert response.status_code == 422
    assert await _folder_id(db_session, photo) == folder.id
