import hashlib
import hmac
import json
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import stripe
from sqlalchemy import select

from app.config import get_settings
from app.integrations.stripe.client import get_stripe_client
from app.main import app
from app.models.enums import OrderStatus, PhotographerStatus, PhotoStatus, PhotoVisibility, UserRole
from app.models.event import Event
from app.models.order import Order
from app.models.photographer import Photo, Photographer, PhotoPurchase
from app.models.user import User
from tests.factories import make_event

WEBHOOK_SECRET = "whsec_test_secret"
RECEIPT_PATH = "app.services.checkout_service.TransactionalEmailService.send_purchase_receipt"


class FakeSessions:
    def __init__(self):
        self.created = []
        self.retrieve_results = {}

    async def create_async(self, params, options=None):
        self.created.append((params, options))
        session_id = f"cs_test_{len(self.created)}"
        return SimpleNamespace(id=session_id, url=f"https://checkout.stripe.test/{session_id}")

    async def retrieve_async(self, session_id, params=None, options=None):
        return self.retrieve_results[session_id]


class FakeStripeClient:
    """Fakes Stripe's network calls; webhook signatures are checked by the real library."""

    def __init__(self):
        self.sessions = FakeSessions()
        self.v1 = SimpleNamespace(checkout=SimpleNamespace(sessions=self.sessions))
        self._real = stripe.StripeClient("sk_test_dummy")

    def construct_event(self, payload, sig_header, secret):
        return self._real.construct_event(payload, sig_header, secret)


@pytest.fixture
def fake_stripe(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
    monkeypatch.setenv("STRIPE_CONNECT_WEBHOOK_SECRET", "")  # ignore a local .env value
    monkeypatch.setenv("API_PUBLIC_BASE_URL", "https://api.gallopics.test")
    monkeypatch.setenv("FRONTEND_BASE_URL", "https://gallopics.test")
    get_settings.cache_clear()
    fake = FakeStripeClient()
    app.dependency_overrides[get_stripe_client] = lambda: fake
    yield fake
    get_settings.cache_clear()


async def _make_photo(db_session, status=PhotoStatus.READY):
    photographer_user = User(
        clerk_user_id=f"clerk_pg_{status.value}",
        email=f"pg-{status.value}@example.com",
        role=UserRole.PHOTOGRAPHER,
    )
    db_session.add(photographer_user)
    await db_session.flush()
    photographer = Photographer(
        user_id=photographer_user.id,
        slug=f"pg-{status.value}",
        display_name="Test Photographer",
        status=PhotographerStatus.APPROVED,
    )
    db_session.add(photographer)
    event = Event(**make_event(name="Checkout Event"))
    db_session.add(event)
    await db_session.flush()
    photo = Photo(
        event_id=event.id,
        photographer_id=photographer.id,
        storage_key_original="originals/photo.jpg",
        price=10000,
        status=status,
        visibility=PhotoVisibility.PUBLISHED,
    )
    db_session.add(photo)
    await db_session.flush()
    return photo


async def _start_checkout(async_client, photo, quality="high"):
    response = await async_client.post(
        "/api/v1/checkout/sessions",
        json={
            "items": [{"photo_id": str(photo.id), "quality": quality}],
            "customer_email": "buyer@example.com",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _session_object(session_id, **overrides):
    return {
        "id": session_id,
        "object": "checkout.session",
        "payment_status": "paid",
        "amount_total": 99900,
        "currency": "sek",
        "payment_intent": "pi_test_1",
        **overrides,
    }


async def _send_webhook(async_client, event_type, session, secret=WEBHOOK_SECRET):
    payload = json.dumps(
        {
            "id": "evt_test_1",
            "object": "event",
            "type": event_type,
            "data": {"object": session},
        }
    )
    timestamp = int(time.time())
    signature = hmac.new(secret.encode(), f"{timestamp}.{payload}".encode(), hashlib.sha256).hexdigest()
    return await async_client.post(
        "/api/v1/checkout/webhook/stripe",
        content=payload,
        headers={"stripe-signature": f"t={timestamp},v1={signature}", "content-type": "application/json"},
    )


async def _order(db_session, order_id):
    result = await db_session.execute(
        select(Order).where(Order.id == uuid.UUID(str(order_id))).execution_options(populate_existing=True)
    )
    return result.scalar_one()


async def test_create_session_prices_on_server(async_client, db_session, fake_stripe):
    photo = await _make_photo(db_session)
    data = await _start_checkout(async_client, photo, quality="high")

    assert data["checkout_url"] == "https://checkout.stripe.test/cs_test_1"
    params, options = fake_stripe.sessions.created[0]
    assert params["mode"] == "payment"
    assert params["customer_email"] == "buyer@example.com"
    assert params["line_items"][0]["price_data"]["unit_amount"] == 99900
    assert params["line_items"][0]["price_data"]["currency"] == "sek"
    assert params["success_url"] == "https://gallopics.test/cart/success?session_id={CHECKOUT_SESSION_ID}"
    assert params["cancel_url"] == "https://gallopics.test/cart"
    assert params["metadata"]["order_id"] == data["order_id"]
    assert options["idempotency_key"] == f"checkout-session-{data['order_id']}"

    order = await _order(db_session, data["order_id"])
    assert order.amount == 99900
    assert order.status == OrderStatus.PENDING
    assert order.stripe_checkout_session_id == "cs_test_1"
    assert order.line_items[0]["photographer_id"] == str(photo.photographer_id)


async def test_create_session_merges_duplicate_items(async_client, db_session, fake_stripe):
    photo = await _make_photo(db_session)
    item = {"photo_id": str(photo.id), "quality": "web"}
    response = await async_client.post(
        "/api/v1/checkout/sessions",
        json={"items": [item, item], "customer_email": "buyer@example.com"},
    )
    assert response.status_code == 200
    params, _ = fake_stripe.sessions.created[0]
    assert len(params["line_items"]) == 1


async def test_create_session_rejects_unknown_quality(async_client, db_session, fake_stripe):
    photo = await _make_photo(db_session)
    response = await async_client.post(
        "/api/v1/checkout/sessions",
        json={"items": [{"photo_id": str(photo.id), "quality": "free"}], "customer_email": "buyer@example.com"},
    )
    assert response.status_code == 400
    assert fake_stripe.sessions.created == []


async def test_create_session_rejects_unavailable_photo(async_client, db_session, fake_stripe):
    photo = await _make_photo(db_session, status=PhotoStatus.PROCESSING)
    response = await async_client.post(
        "/api/v1/checkout/sessions",
        json={"items": [{"photo_id": str(photo.id), "quality": "web"}], "customer_email": "buyer@example.com"},
    )
    assert response.status_code == 400


async def test_create_session_requires_email(async_client, db_session, fake_stripe):
    photo = await _make_photo(db_session)
    response = await async_client.post(
        "/api/v1/checkout/sessions",
        json={"items": [{"photo_id": str(photo.id), "quality": "web"}], "customer_email": "not-an-email"},
    )
    assert response.status_code == 422


async def test_webhook_fulfils_order_once(async_client, db_session, fake_stripe):
    photo = await _make_photo(db_session)
    data = await _start_checkout(async_client, photo)
    session = _session_object(data["session_id"])

    with patch(RECEIPT_PATH, new_callable=AsyncMock) as send_receipt:
        send_receipt.return_value = {"status": "sent"}
        first = await _send_webhook(async_client, "checkout.session.completed", session)
        second = await _send_webhook(async_client, "checkout.session.completed", session)

    assert first.status_code == 200
    assert second.status_code == 200
    order = await _order(db_session, data["order_id"])
    assert order.status == OrderStatus.CAPTURED
    assert order.stripe_payment_intent_id == "pi_test_1"

    purchases = (await db_session.execute(select(PhotoPurchase))).scalars().all()
    assert len(purchases) == 1
    assert purchases[0].quality == "high"
    assert purchases[0].amount == 99900

    send_receipt.assert_awaited_once()
    receipt_item = send_receipt.await_args.kwargs["line_items"][0]
    assert send_receipt.await_args.kwargs["recipient_email"] == "buyer@example.com"
    assert receipt_item["download_url"] == (
        f"https://api.gallopics.test/api/v1/photos/{photo.id}/download"
        f"?order_id={data['order_id']}&inline=true"
    )

    download = await async_client.post(f"/api/v1/photos/{photo.id}/download", json={"order_id": data["order_id"]})
    assert download.status_code == 200


async def test_webhook_rejects_bad_signature(async_client, db_session, fake_stripe):
    photo = await _make_photo(db_session)
    data = await _start_checkout(async_client, photo)
    response = await _send_webhook(
        async_client,
        "checkout.session.completed",
        _session_object(data["session_id"]),
        secret="whsec_wrong",
    )
    assert response.status_code == 400
    order = await _order(db_session, data["order_id"])
    assert order.status == OrderStatus.PENDING


async def test_webhook_ignores_unpaid_session(async_client, db_session, fake_stripe):
    photo = await _make_photo(db_session)
    data = await _start_checkout(async_client, photo)
    response = await _send_webhook(
        async_client,
        "checkout.session.completed",
        _session_object(data["session_id"], payment_status="unpaid"),
    )
    assert response.status_code == 200
    order = await _order(db_session, data["order_id"])
    assert order.status == OrderStatus.PENDING


async def test_webhook_amount_mismatch_does_not_fulfil(async_client, db_session, fake_stripe):
    photo = await _make_photo(db_session)
    data = await _start_checkout(async_client, photo)
    response = await _send_webhook(
        async_client,
        "checkout.session.completed",
        _session_object(data["session_id"], amount_total=100),
    )
    assert response.status_code == 200
    order = await _order(db_session, data["order_id"])
    assert order.status == OrderStatus.PENDING


async def test_webhook_expired_session_cancels_order(async_client, db_session, fake_stripe):
    photo = await _make_photo(db_session)
    data = await _start_checkout(async_client, photo)
    response = await _send_webhook(
        async_client,
        "checkout.session.expired",
        _session_object(data["session_id"], payment_status="unpaid"),
    )
    assert response.status_code == 200
    order = await _order(db_session, data["order_id"])
    assert order.status == OrderStatus.CANCELLED


async def test_webhook_unknown_session_is_acknowledged(async_client, db_session, fake_stripe):
    response = await _send_webhook(async_client, "checkout.session.completed", _session_object("cs_unknown"))
    assert response.status_code == 200


async def test_success_page_confirms_payment_without_webhook(async_client, db_session, fake_stripe):
    photo = await _make_photo(db_session)
    data = await _start_checkout(async_client, photo)
    fake_stripe.sessions.retrieve_results[data["session_id"]] = stripe.StripeObject.construct_from(
        _session_object(data["session_id"]), "sk_test_dummy"
    )

    with patch(RECEIPT_PATH, new_callable=AsyncMock) as send_receipt:
        send_receipt.return_value = {"status": "sent"}
        response = await async_client.get(f"/api/v1/checkout/sessions/{data['session_id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["paid"] is True
    assert body["status"] == "captured"
    assert body["customer_email"] == "buyer@example.com"
    assert body["items"][0]["photo_id"] == str(photo.id)
    assert body["items"][0]["amount"] == 99900
    send_receipt.assert_awaited_once()


async def test_success_page_unknown_session(async_client, fake_stripe):
    response = await async_client.get("/api/v1/checkout/sessions/cs_unknown")
    assert response.status_code == 404


async def test_create_session_uses_cancel_path(async_client, db_session, fake_stripe):
    photo = await _make_photo(db_session)
    response = await async_client.post(
        "/api/v1/checkout/sessions",
        json={
            "items": [{"photo_id": str(photo.id), "quality": "web"}],
            "customer_email": "buyer@example.com",
            "cancel_path": f"/photo/{photo.id}?from=epro",
        },
    )
    assert response.status_code == 200
    params, _ = fake_stripe.sessions.created[0]
    assert params["cancel_url"] == f"https://gallopics.test/photo/{photo.id}?from=epro"


@pytest.mark.parametrize("cancel_path", ["//evil.com", "/\\evil.com", "https://evil.com", "photo/1", "/a b"])
async def test_create_session_rejects_offsite_cancel_path(async_client, db_session, fake_stripe, cancel_path):
    photo = await _make_photo(db_session)
    response = await async_client.post(
        "/api/v1/checkout/sessions",
        json={
            "items": [{"photo_id": str(photo.id), "quality": "web"}],
            "customer_email": "buyer@example.com",
            "cancel_path": cancel_path,
        },
    )
    assert response.status_code == 422
    assert fake_stripe.sessions.created == []
