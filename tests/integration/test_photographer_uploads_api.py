import uuid

from app.models.enums import PhotographerStatus
from app.models.event import Event
from app.models.photographer import Photographer
from app.storage.local import LocalStorageBackend
from tests.factories import make_event

PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?"
    b"\x00\x05\xfe\x02\xfeA\xe2!\xbc\x00\x00\x00\x00IEND\xaeB`\x82"
)


async def _seed_photographer(db_session, photographer_user):
    photographer = Photographer(
        user_id=photographer_user.id,
        slug="upload-photographer",
        display_name="Upload Photographer",
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


async def test_upload_photos_accepts_multipart_payload(
    async_client,
    db_session,
    photographer_user,
    photographer_auth_headers,
    monkeypatch,
    tmp_path,
):
    import app.routers.photographer as photographer_router

    await _seed_photographer(db_session, photographer_user)
    event = await _seed_event(db_session, name="Uploadable Event")
    monkeypatch.setattr(
        photographer_router,
        "_get_storage",
        lambda: LocalStorageBackend(str(tmp_path / "uploads")),
    )

    response = await async_client.post(
        "/api/v1/photographer/uploads",
        headers=photographer_auth_headers,
        data={"event_id": str(event.id)},
        files={"files": ("test.png", PNG_1X1, "image/png")},
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["event_id"] == str(event.id)
    assert data[0]["status"] == "ready"
    assert data[0]["tags"] == []


async def test_upload_photos_stores_class_ids(
    async_client,
    db_session,
    photographer_user,
    photographer_auth_headers,
    monkeypatch,
    tmp_path,
):
    import app.routers.photographer as photographer_router

    await _seed_photographer(db_session, photographer_user)
    event = await _seed_event(db_session, name="Class Upload Event")
    class_id = uuid.uuid4()
    monkeypatch.setattr(
        photographer_router,
        "_get_storage",
        lambda: LocalStorageBackend(str(tmp_path / "uploads")),
    )

    response = await async_client.post(
        "/api/v1/photographer/uploads",
        headers=photographer_auth_headers,
        data={
            "event_id": str(event.id),
            "class_id": str(class_id),
            "class_section_id": str(class_id),
        },
        files={"files": ("test.png", PNG_1X1, "image/png")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data[0]["class_id"] == str(class_id)
    assert data[0]["class_section_id"] == str(class_id)


async def test_upload_photos_stores_external_event_class_id(
    async_client,
    db_session,
    photographer_user,
    photographer_auth_headers,
    monkeypatch,
    tmp_path,
):
    import app.routers.photographer as photographer_router

    await _seed_photographer(db_session, photographer_user)
    event = await _seed_event(db_session, name="Equipe Class Upload Event")
    monkeypatch.setattr(
        photographer_router,
        "_get_storage",
        lambda: LocalStorageBackend(str(tmp_path / "uploads")),
    )

    response = await async_client.post(
        "/api/v1/photographer/uploads",
        headers=photographer_auth_headers,
        data={
            "event_id": str(event.id),
            "event_class_id": "1198540",
            "class_name": "D09 · Prix St-Georges · CDI1*",
        },
        files={"files": ("test.png", PNG_1X1, "image/png")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data[0]["class_id"] is None
    assert data[0]["class_section_id"] is None
    assert data[0]["event_class_id"] == "1198540"
    assert data[0]["class_name"] == "D09 · Prix St-Georges · CDI1*"


async def test_upload_photos_rejects_invalid_event_id(
    async_client,
    db_session,
    photographer_user,
    photographer_auth_headers,
    tmp_path,
    monkeypatch,
):
    import app.routers.photographer as photographer_router

    await _seed_photographer(db_session, photographer_user)
    monkeypatch.setattr(
        photographer_router,
        "_get_storage",
        lambda: LocalStorageBackend(str(tmp_path / "uploads")),
    )

    response = await async_client.post(
        "/api/v1/photographer/uploads",
        headers=photographer_auth_headers,
        data={"event_id": "not-a-uuid"},
        files={"files": ("test.png", PNG_1X1, "image/png")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid event_id"
