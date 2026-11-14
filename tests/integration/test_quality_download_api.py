from dataclasses import replace
from io import BytesIO
from unittest.mock import patch

import pytest
from PIL import Image
from sqlalchemy import select

from app.models.enums import OrderStatus
from app.models.photographer import PhotoPurchase
from tests.integration.test_media_access_api import _seed_photo, _seed_purchase, _use_storage


async def _purchase(db_session, photographer_user, tmp_path, size=(4000, 6000), orientation=None):
    _, photo = await _seed_photo(db_session, photographer_user, tmp_path)
    original = tmp_path / photo.storage_key_original
    image = Image.new("RGB", size, "#345678")
    exif = Image.Exif()
    if orientation:
        exif[274] = orientation
    image.save(original, format="JPEG", exif=exif)
    order = await _seed_purchase(db_session, photo, OrderStatus.CAPTURED)
    purchase = (await db_session.execute(select(PhotoPurchase))).scalar_one()
    purchase.quality = "web"
    await db_session.flush()
    return photo, order, original.read_bytes()


async def test_web_download_resizes_and_reuses_private_cache(async_client, db_session, photographer_user, monkeypatch, tmp_path):
    _use_storage(monkeypatch, tmp_path)
    photo, order, _ = await _purchase(db_session, photographer_user, tmp_path)
    params = {"order_id": str(order.id), "quality": "web"}
    response = await async_client.get(f"/api/v1/photos/{photo.id}/download", params=params)
    assert response.status_code == 200
    assert Image.open(BytesIO(response.content)).size == (720, 1080)
    cached = tmp_path / f"downloads/{photo.id}/web.jpg"
    assert cached.read_bytes() == response.content
    with patch("app.services.download_service._resize_download", side_effect=AssertionError("cache miss")):
        repeated = await async_client.get(f"/api/v1/photos/{photo.id}/download", params=params)
    assert repeated.content == response.content
    assert (await async_client.get(f"/uploads/downloads/{photo.id}/web.jpg")).status_code == 404
    missing = await async_client.get(f"/api/v1/photos/{photo.id}/download", params={"order_id": "00000000-0000-0000-0000-000000000000", "quality": "web"})
    assert missing.status_code == 404


@pytest.mark.parametrize("size,orientation,expected", [((400,600),None,(400,600)), ((6000,4000),6,(720,1080))])
async def test_web_never_upscales_and_applies_exif(async_client, db_session, photographer_user, monkeypatch, tmp_path, size, orientation, expected):
    _use_storage(monkeypatch, tmp_path)
    photo, order, _ = await _purchase(db_session, photographer_user, tmp_path, size, orientation)
    result = await async_client.get(f"/api/v1/photos/{photo.id}/download", params={"order_id": str(order.id), "quality":"web"})
    assert result.status_code == 200
    assert Image.open(BytesIO(result.content)).size == expected


async def test_same_photo_two_qualities_and_original_bytes(async_client, db_session, photographer_user, monkeypatch, tmp_path):
    _use_storage(monkeypatch, tmp_path)
    photo, order, original = await _purchase(db_session, photographer_user, tmp_path)
    for quality in ["high", "commercial"]:
        db_session.add(PhotoPurchase(order_id=order.id, user_id=order.user_id, photo_id=photo.id, quality=quality, amount=99900))
    await db_session.flush()
    for quality in ["web", "high", "commercial"]:
        link = await async_client.post(f"/api/v1/photos/{photo.id}/download", json={"order_id": str(order.id), "quality": quality})
        assert link.status_code == 200
        assert f"quality={quality}" in link.json()["url"]
        result = await async_client.get(link.json()["url"])
        assert result.status_code == 200
        if quality != "web":
            assert result.content == original
    ambiguous = await async_client.get(f"/api/v1/photos/{photo.id}/download", params={"order_id": str(order.id)})
    assert ambiguous.status_code == 400


async def test_unpurchased_quality_is_forbidden(async_client, db_session, photographer_user, monkeypatch, tmp_path):
    _use_storage(monkeypatch, tmp_path)
    photo, order, _ = await _purchase(db_session, photographer_user, tmp_path)
    response = await async_client.get(f"/api/v1/photos/{photo.id}/download", params={"order_id": str(order.id), "quality": "high"})
    assert response.status_code == 403


async def test_size_config_change_invalidates_cache(async_client, db_session, photographer_user, monkeypatch, tmp_path):
    from app.services.pricing import QUALITY_TIERS
    _use_storage(monkeypatch, tmp_path)
    photo, order, _ = await _purchase(db_session, photographer_user, tmp_path)
    params = {"order_id": str(order.id), "quality":"web"}
    await async_client.get(f"/api/v1/photos/{photo.id}/download", params=params)
    monkeypatch.setitem(QUALITY_TIERS, "web", replace(QUALITY_TIERS["web"], max_long_side=600))
    response = await async_client.get(f"/api/v1/photos/{photo.id}/download", params=params)
    assert Image.open(BytesIO(response.content)).size == (400, 600)


async def test_deleting_unsold_photo_removes_all_download_caches(async_client, db_session, photographer_user, photographer_auth_headers, monkeypatch, tmp_path):
    from app.services.download_service import download_cache_keys
    _use_storage(monkeypatch, tmp_path)
    _, photo = await _seed_photo(db_session, photographer_user, tmp_path)
    for key in download_cache_keys(photo.id):
        file = tmp_path / key
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"cached")
    response = await async_client.delete(f"/api/v1/photographer/photos/{photo.id}", headers=photographer_auth_headers)
    assert response.status_code == 204
    assert all(not (tmp_path / key).exists() for key in download_cache_keys(photo.id))
