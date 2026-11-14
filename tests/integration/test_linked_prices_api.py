import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy import select

from app.models.enums import PhotographerStatus
from app.models.photographer import PhotoPurchase
from app.services.checkout_service import CheckoutService
from app.config import Settings
from app.schemas.checkout import CheckoutItem
from tests.integration.test_photo_prices_api import _seed_photo, _seed_photographer, DEFAULT_PRICES
from tests.integration.test_checkout_api import fake_stripe, _start_checkout, _send_webhook, _session_object, RECEIPT_PATH


async def test_linked_prices_resolve_and_clear_overrides(async_client, db_session, photographer_user, photographer_auth_headers):
    photographer = await _seed_photographer(db_session, photographer_user)
    photo = await _seed_photo(db_session, photographer)
    url = "/api/v1/photographer/me/prices"
    initial = await async_client.get(url, headers=photographer_auth_headers)
    assert initial.status_code == 200
    assert initial.json() == {"defaults": {"web":None,"high":None,"commercial":None}, "effective":DEFAULT_PRICES}
    updated = await async_client.patch(url, headers=photographer_auth_headers, json={"web": 7900,"high":129900})
    assert updated.status_code == 200
    assert updated.json()["effective"] == {**DEFAULT_PRICES,"web":7900,"high":129900}
    public = await async_client.get(f"/api/v1/photos/{photo.id}")
    assert public.json()["prices"]["web"] == 7900
    override = await async_client.patch("/api/v1/photographer/photos", headers=photographer_auth_headers, json={"photo_ids":[str(photo.id)],"prices":{"web":9900}})
    assert override.json()[0]["prices"]["web"] == 9900
    assert override.json()[0]["own_prices"] == {"web":9900,"high":None,"commercial":None}
    await async_client.patch(url, headers=photographer_auth_headers, json={"web":8900})
    assert (await async_client.get(f"/api/v1/photos/{photo.id}")).json()["prices"]["web"] == 9900
    cleared = await async_client.patch("/api/v1/photographer/photos", headers=photographer_auth_headers, json={"photo_ids":[str(photo.id)],"prices":{"web":None}})
    assert cleared.status_code == 200
    assert cleared.json()[0]["prices"]["web"] == 8900
    assert cleared.json()[0]["own_prices"]["web"] is None
    reset = await async_client.patch(url, headers=photographer_auth_headers, json={"web":None})
    assert reset.json()["effective"]["web"] == 49900
    assert (await async_client.get(f"/api/v1/photos/{photo.id}")).json()["prices"]["web"] == 49900


async def test_checkout_resolves_linked_prices_and_preserves_purchase_amount(async_client, db_session, photographer_user, photographer_auth_headers):
    photographer = await _seed_photographer(db_session, photographer_user)
    photo = await _seed_photo(db_session, photographer)
    await async_client.patch("/api/v1/photographer/me/prices", headers=photographer_auth_headers, json={"web": 7900})
    service = CheckoutService(db_session, None, Settings(_env_file=None,debug=False), "http://localhost:8000")
    line = await service._price_items([CheckoutItem(photo_id=photo.id, quality="web")])
    assert line[0]["total_amount"] == 7900
    photo.price_web = 9900
    await db_session.flush()
    line = await service._price_items([CheckoutItem(photo_id=photo.id, quality="web")])
    assert line[0]["total_amount"] == 9900


async def test_checkout_charge_and_sale_keep_price_at_purchase(async_client, db_session, photographer_user, photographer_auth_headers, fake_stripe):
    photographer = await _seed_photographer(db_session, photographer_user)
    photo = await _seed_photo(db_session, photographer)
    await async_client.patch("/api/v1/photographer/me/prices", headers=photographer_auth_headers, json={"web":7900})
    checkout = await _start_checkout(async_client, photo, "web")
    assert fake_stripe.sessions.created[-1][0]["line_items"][0]["price_data"]["unit_amount"] == 7900
    await async_client.patch("/api/v1/photographer/me/prices", headers=photographer_auth_headers, json={"web":8900})
    with patch(RECEIPT_PATH,new_callable=AsyncMock) as receipt:
        receipt.return_value = {"status":"skipped"}
        response = await _send_webhook(async_client,"checkout.session.completed",_session_object(checkout["session_id"],amount_total=7900))
    assert response.status_code == 200
    purchase = (await db_session.execute(select(PhotoPurchase))).scalar_one()
    assert purchase.amount == 7900
    sales = await async_client.get("/api/v1/photographer/sales",headers=photographer_auth_headers)
    assert sales.status_code == 200
    assert sales.json()["items"][0]["amount"] == 7900


@pytest.mark.parametrize("status", [PhotographerStatus.PENDING, PhotographerStatus.SUSPENDED])
async def test_defaults_require_approved_photographer(async_client, db_session, photographer_user, photographer_auth_headers, status):
    await _seed_photographer(db_session, photographer_user, status)
    for method in ["get", "patch"]:
        result = await getattr(async_client,method)("/api/v1/photographer/me/prices", headers=photographer_auth_headers, **({"json":{"web":7900}} if method == "patch" else {}))
        assert result.status_code == 403


@pytest.mark.parametrize("value", [4800,1000100,49901,-100,0])
async def test_default_price_validation(async_client, db_session, photographer_user, photographer_auth_headers, value):
    await _seed_photographer(db_session, photographer_user)
    result = await async_client.patch("/api/v1/photographer/me/prices", headers=photographer_auth_headers, json={"web":value})
    assert result.status_code == 422
