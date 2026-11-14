import json

import httpx
import pytest
import respx

from app.config import Settings
from app.models.enums import PhotographerStatus
from app.models.photographer import Photographer


@pytest.mark.parametrize("previous", [PhotographerStatus.PENDING, PhotographerStatus.SUSPENDED])
@respx.mock
async def test_approval_sends_email_once(async_client, admin_auth_headers, db_session, photographer_user, monkeypatch, previous):
    settings = Settings(_env_file=None, debug=False, transactional_email_enabled=True, resend_api_key="test-key")
    monkeypatch.setattr("app.routers.admin.get_settings", lambda: settings)
    sent = respx.post("https://api.resend.com/emails").mock(return_value=httpx.Response(200, json={"id": "test-email"}))
    photographer = Photographer(user_id=photographer_user.id, slug="approval-email", display_name="Photographer", status=previous)
    db_session.add(photographer)
    await db_session.flush()
    url = f"/api/v1/admin/photographers/{photographer.id}"
    response = await async_client.patch(url, json={"status": "approved"}, headers=admin_auth_headers)
    assert response.status_code == 200
    assert sent.call_count == 1
    payload = json.loads(sent.calls[0].request.content)
    assert payload["subject"] == "Your Gallopics account is approved"
    assert payload["to"] == [photographer_user.email]
    assert "http://localhost:5173/pg" in payload["html"]
    assert "http://localhost:5173/pg" in payload["text"]
    assert (await async_client.patch(url, json={"status": "approved"}, headers=admin_auth_headers)).status_code == 200
    assert sent.call_count == 1


@pytest.mark.parametrize("mode", ["disabled", "no-email", "rejected", "failure"])
@respx.mock
async def test_approval_email_does_not_block_status(async_client, admin_auth_headers, db_session, photographer_user, monkeypatch, mode):
    settings = Settings(_env_file=None, debug=False, transactional_email_enabled=mode != "disabled", resend_api_key="test-key")
    monkeypatch.setattr("app.routers.admin.get_settings", lambda: settings)
    sent = respx.post("https://api.resend.com/emails").mock(return_value=httpx.Response(500, json={"error": "unavailable"}))
    if mode == "no-email":
        photographer_user.email = ""
    photographer = Photographer(user_id=photographer_user.id, slug="approval-email", display_name="Photographer")
    db_session.add(photographer)
    await db_session.flush()
    status = "suspended" if mode == "rejected" else "approved"
    response = await async_client.patch(f"/api/v1/admin/photographers/{photographer.id}", json={"status": status}, headers=admin_auth_headers)
    assert response.status_code == 200
    assert response.json()["status"] == status
    assert sent.call_count == (1 if mode == "failure" else 0)
    await db_session.refresh(photographer)
    assert photographer.status.value == status
