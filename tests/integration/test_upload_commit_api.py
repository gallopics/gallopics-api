from unittest.mock import AsyncMock

from tests.integration.test_photographer_uploads_api import PNG_1X1, _seed_event, _seed_photographer
from app.storage.local import LocalStorageBackend


async def test_upload_commits_before_returning_photo_ids(async_client, db_session, photographer_user, photographer_auth_headers, monkeypatch, tmp_path):
    await _seed_photographer(db_session, photographer_user)
    event = await _seed_event(db_session, name="Upload commit test")
    monkeypatch.setattr("app.routers.photographer._get_storage", lambda: LocalStorageBackend(str(tmp_path)))
    committed = AsyncMock(wraps=db_session.commit)
    monkeypatch.setattr(db_session, "commit", committed)
    response = await async_client.post("/api/v1/photographer/uploads", headers=photographer_auth_headers, data={"event_id":str(event.id)}, files={"files": ("test.png",PNG_1X1,"image/png")})
    assert response.status_code == 200
    committed.assert_awaited_once()
    photo_id = response.json()[0]["id"]
    patch = await async_client.patch(f"/api/v1/photographer/photos/{photo_id}", headers=photographer_auth_headers, json={"class_name":"Updated immediately"})
    assert patch.status_code == 200


async def test_complete_upload_commits_before_returning_photo_ids(async_client, db_session, photographer_user, photographer_auth_headers, monkeypatch, tmp_path):
    photographer = await _seed_photographer(db_session, photographer_user)
    event = await _seed_event(db_session, name="Complete upload commit test")
    source = tmp_path / "originals/test.png"
    source.parent.mkdir()
    source.write_bytes(PNG_1X1)
    monkeypatch.setattr("app.routers.photographer._get_storage", lambda: LocalStorageBackend(str(tmp_path)))
    monkeypatch.setattr("app.services.photographer_service.PhotographerService.get_upload_session", AsyncMock(return_value={"photographer_id":str(photographer.id), "event_id":str(event.id), "storage_keys":["originals/test.png"]}))
    committed = AsyncMock(wraps=db_session.commit)
    monkeypatch.setattr(db_session, "commit", committed)
    response = await async_client.post("/api/v1/photographer/uploads/complete", headers=photographer_auth_headers, json={"session_id":"test-session"})
    assert response.status_code == 200
    committed.assert_awaited_once()
