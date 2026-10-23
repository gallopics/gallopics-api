import uuid
from types import SimpleNamespace

import pytest

from app.integrations.stripe.client import get_stripe_client
from app.main import app
from app.models.enums import OrderStatus
from app.models.order import Order


class FakeRefunds:
    def __init__(self):
        self.created = []

    async def create_async(self, params, options=None):
        self.created.append((params, options))
        return SimpleNamespace(id="re_test_1")


@pytest.fixture
def fake_refunds():
    refunds = FakeRefunds()
    fake = SimpleNamespace(v1=SimpleNamespace(refunds=refunds))
    app.dependency_overrides[get_stripe_client] = lambda: fake
    return refunds


async def _create_order(db_session, user_id, status=OrderStatus.CAPTURED, payment_intent="pi_test_1"):
    order = Order(
        user_id=user_id,
        amount=5000,
        currency="SEK",
        status=status,
        stripe_payment_intent_id=payment_intent,
    )
    db_session.add(order)
    await db_session.flush()
    return order


async def test_get_order_as_owner(async_client, auth_headers, db_session):
    # The auth_headers user gets auto-created on first request
    r = await async_client.get("/api/v1/me", headers=auth_headers)
    user_id = r.json()["id"]

    order = await _create_order(db_session, uuid.UUID(user_id))
    response = await async_client.get(f"/api/v1/orders/{order.id}", headers=auth_headers)
    assert response.status_code == 200


async def test_get_order_not_found(async_client, auth_headers):
    response = await async_client.get(f"/api/v1/orders/{uuid.uuid4()}", headers=auth_headers)
    assert response.status_code == 404


async def test_refund_requires_admin(async_client, auth_headers, db_session, fake_refunds):
    r = await async_client.get("/api/v1/me", headers=auth_headers)
    order = await _create_order(db_session, uuid.UUID(r.json()["id"]))
    response = await async_client.post(f"/api/v1/orders/{order.id}/refund", headers=auth_headers)
    assert response.status_code == 403
    assert fake_refunds.created == []


async def test_refund_success(async_client, admin_auth_headers, db_session, admin_user, fake_refunds):
    order = await _create_order(db_session, admin_user.id)
    response = await async_client.post(f"/api/v1/orders/{order.id}/refund", headers=admin_auth_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "refunded"
    assert fake_refunds.created == [({"payment_intent": "pi_test_1"}, {"idempotency_key": f"refund-{order.id}"})]


async def test_refund_invalid_state(async_client, admin_auth_headers, db_session, admin_user, fake_refunds):
    order = await _create_order(db_session, admin_user.id, status=OrderStatus.PENDING)
    response = await async_client.post(f"/api/v1/orders/{order.id}/refund", headers=admin_auth_headers)
    assert response.status_code == 409


async def test_refund_without_stripe_payment(async_client, admin_auth_headers, db_session, admin_user, fake_refunds):
    order = await _create_order(db_session, admin_user.id, payment_intent=None)
    response = await async_client.post(f"/api/v1/orders/{order.id}/refund", headers=admin_auth_headers)
    assert response.status_code == 409
    assert fake_refunds.created == []
