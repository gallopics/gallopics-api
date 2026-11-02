import httpx

from app.models.enums import OrderStatus, PhotographerStatus, PhotoStatus, PhotoTagType, PhotoVisibility
from app.models.event import Event
from app.models.order import Order
from app.models.photographer import Photo, Photographer, PhotoPurchase, PhotoTag
from app.models.user import User
from app.storage.local import LocalStorageBackend
from tests.factories import make_event, make_order, make_user

ORIGINAL_BYTES = b"original-unwatermarked"
PREVIEW_BYTES = b"preview-watermarked"
THUMBNAIL_BYTES = b"thumbnail-small"


def _write(storage_dir, key, data):
    path = storage_dir / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _use_storage(monkeypatch, storage_dir):
    import app.routers.gallery as gallery_router
    import app.routers.photographer as photographer_router

    monkeypatch.setattr(photographer_router, "_get_storage", lambda: LocalStorageBackend(str(storage_dir)))
    monkeypatch.setattr(gallery_router, "get_storage_backend", lambda _settings: LocalStorageBackend(str(storage_dir)))


async def _seed_photo(db_session, photographer_user, storage_dir, *, preview=True, thumbnail=True):
    photographer = Photographer(
        user_id=photographer_user.id,
        slug="media-photographer",
        display_name="Media Photographer",
        status=PhotographerStatus.APPROVED,
    )
    event = Event(**make_event(name="Media Event"))
    db_session.add_all([photographer, event])
    await db_session.flush()

    original_key = f"originals/{event.id}/session/IMG_0001.jpg"
    photo = Photo(
        event_id=event.id,
        photographer_id=photographer.id,
        storage_key_original=original_key,
        storage_key_preview=original_key.replace("originals/", "previews/") if preview else None,
        storage_key_thumbnail=original_key.replace("originals/", "thumbnails/") if thumbnail else None,
        price=10000,
        status=PhotoStatus.READY,
        visibility=PhotoVisibility.PUBLISHED,
    )
    db_session.add(photo)
    await db_session.flush()
    db_session.add(PhotoTag(photo_id=photo.id, type=PhotoTagType.RIDER, value="Anna Svensson"))
    await db_session.flush()

    _write(storage_dir, photo.storage_key_original, ORIGINAL_BYTES)
    if photo.storage_key_preview:
        _write(storage_dir, photo.storage_key_preview, PREVIEW_BYTES)
    if photo.storage_key_thumbnail:
        _write(storage_dir, photo.storage_key_thumbnail, THUMBNAIL_BYTES)
    return event, photo


async def _seed_purchase(db_session, photo, status):
    buyer = User(**make_user(email="buyer@example.com"))
    db_session.add(buyer)
    await db_session.flush()
    order = Order(**make_order(user_id=buyer.id, status=status))
    db_session.add(order)
    await db_session.flush()
    db_session.add(
        PhotoPurchase(order_id=order.id, user_id=buyer.id, photo_id=photo.id, quality="high", amount=5000)
    )
    await db_session.flush()
    return order


async def test_guest_cannot_fetch_upload_files_except_avatars(monkeypatch, tmp_path):
    import app.main as main
    from app.config import get_settings

    settings = get_settings().model_copy(update={"storage_local_path": str(tmp_path)})
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    app = main.create_app()

    _write(tmp_path, "originals/event/session/IMG_0001.jpg", ORIGINAL_BYTES)
    _write(tmp_path, "previews/event/session/IMG_0001.jpg", PREVIEW_BYTES)
    _write(tmp_path, "thumbnails/event/session/IMG_0001.jpg", THUMBNAIL_BYTES)
    _write(tmp_path, "avatars/user/avatar.png", b"avatar")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for path in [
            "/uploads/originals/event/session/IMG_0001.jpg",
            "/uploads/previews/event/session/IMG_0001.jpg",
            "/uploads/thumbnails/event/session/IMG_0001.jpg",
            "/uploads/avatars/%2e%2e/originals/event/session/IMG_0001.jpg",
        ]:
            for method in ["GET", "HEAD"]:
                response = await client.request(method, path)
                assert response.status_code == 404, f"{method} {path}"
                assert ORIGINAL_BYTES not in response.content

        avatar = await client.get("/uploads/avatars/user/avatar.png")
        assert avatar.status_code == 200
        assert avatar.content == b"avatar"


async def test_public_photo_responses_have_no_storage_keys(
    async_client, db_session, photographer_user, monkeypatch, tmp_path
):
    _use_storage(monkeypatch, tmp_path)
    event, photo = await _seed_photo(db_session, photographer_user, tmp_path)

    responses = [
        await async_client.get(f"/api/v1/events/{event.id}/gallery"),
        await async_client.get(f"/api/v1/events/{event.id}/gallery/search", params={"q": "Anna"}),
        await async_client.get(f"/api/v1/photos/{photo.id}"),
    ]
    for response in responses:
        assert response.status_code == 200
        assert "storage_key" not in response.text
        assert "originals/" not in response.text
        assert "IMG_0001" not in response.text

    detail = responses[-1].json()
    assert detail["preview_url"] == f"/api/v1/photographer/photos/{photo.id}/preview"
    assert detail["thumbnail_url"] == f"/api/v1/photographer/photos/{photo.id}/thumbnail"


async def test_own_photo_responses_show_file_name_without_path(
    async_client, db_session, photographer_user, photographer_auth_headers, monkeypatch, tmp_path
):
    _use_storage(monkeypatch, tmp_path)
    await _seed_photo(db_session, photographer_user, tmp_path)

    response = await async_client.get("/api/v1/photographer/photos", headers=photographer_auth_headers)

    assert response.status_code == 200
    assert response.json()["items"][0]["file_name"] == "IMG_0001.jpg"
    assert "storage_key" not in response.text
    assert "originals/" not in response.text


async def test_thumbnail_and_preview_serve_derivatives(
    async_client, db_session, photographer_user, monkeypatch, tmp_path
):
    _use_storage(monkeypatch, tmp_path)
    _event, photo = await _seed_photo(db_session, photographer_user, tmp_path)

    thumbnail = await async_client.get(f"/api/v1/photographer/photos/{photo.id}/thumbnail")
    preview = await async_client.get(f"/api/v1/photographer/photos/{photo.id}/preview")

    assert thumbnail.status_code == 200
    assert thumbnail.content == THUMBNAIL_BYTES
    assert preview.status_code == 200
    assert preview.content == PREVIEW_BYTES


async def test_thumbnail_falls_back_to_preview(async_client, db_session, photographer_user, monkeypatch, tmp_path):
    _use_storage(monkeypatch, tmp_path)
    _event, photo = await _seed_photo(db_session, photographer_user, tmp_path, thumbnail=False)

    response = await async_client.get(f"/api/v1/photographer/photos/{photo.id}/thumbnail")

    assert response.status_code == 200
    assert response.content == PREVIEW_BYTES


async def test_thumbnail_and_preview_never_serve_the_original(
    async_client, db_session, photographer_user, monkeypatch, tmp_path
):
    _use_storage(monkeypatch, tmp_path)
    _event, photo = await _seed_photo(db_session, photographer_user, tmp_path, preview=False, thumbnail=False)

    for route in ["thumbnail", "preview"]:
        response = await async_client.get(f"/api/v1/photographer/photos/{photo.id}/{route}")
        assert response.status_code == 404
        assert ORIGINAL_BYTES not in response.content


async def test_buyer_with_captured_purchase_downloads_original(
    async_client, db_session, photographer_user, monkeypatch, tmp_path
):
    _use_storage(monkeypatch, tmp_path)
    _event, photo = await _seed_photo(db_session, photographer_user, tmp_path)
    order = await _seed_purchase(db_session, photo, OrderStatus.CAPTURED)

    link = await async_client.post(f"/api/v1/photos/{photo.id}/download", json={"order_id": str(order.id)})
    assert link.status_code == 200

    download = await async_client.get(link.json()["url"])
    assert download.status_code == 200
    assert download.content == ORIGINAL_BYTES


async def test_uncaptured_purchase_cannot_download_original(
    async_client, db_session, photographer_user, monkeypatch, tmp_path
):
    _use_storage(monkeypatch, tmp_path)
    _event, photo = await _seed_photo(db_session, photographer_user, tmp_path)
    order = await _seed_purchase(db_session, photo, OrderStatus.PENDING)

    response = await async_client.get(f"/api/v1/photos/{photo.id}/download", params={"order_id": str(order.id)})

    assert response.status_code == 403
    assert ORIGINAL_BYTES not in response.content
