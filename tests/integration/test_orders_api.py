import uuid

from app.main import app
from app.models.enums import OrderStatus
from app.models.order import Order
from app.routers.orders import get_klarna_client


class FakeKlarnaClient:
    def __init__(self):
        self.captures = []
        self.refunds = []
        self.cancellations = []

    async def capture(self, order_id, payload):
        self.captures.append((order_id, payload))

    async def refund(self, order_id, payload):
        self.refunds.append((order_id, payload))

    async def cancel(self, order_id):
        self.cancellations.append(order_id)


def _override_klarna(fake):
    async def _dependency():
        yield fake

    app.dependency_overrides[get_klarna_client] = _dependency


async def _create_order(db_session, user_id, status=OrderStatus.AUTHORIZED):
    order = Order(user_id=user_id, amount=5000, currency="SEK", status=status)
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


async def test_capture_requires_admin(async_client, auth_headers, db_session):
    r = await async_client.get("/api/v1/me", headers=auth_headers)
    user_id = r.json()["id"]
    order = await _create_order(db_session, uuid.UUID(user_id))
    response = await async_client.post(f"/api/v1/orders/{order.id}/capture", headers=auth_headers)
    assert response.status_code == 403


async def test_capture_success(async_client, admin_auth_headers, db_session, admin_user):
    order = await _create_order(db_session, admin_user.id, status=OrderStatus.AUTHORIZED)
    response = await async_client.post(f"/api/v1/orders/{order.id}/capture", headers=admin_auth_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "captured"


async def test_capture_calls_klarna_for_klarna_order(async_client, admin_auth_headers, db_session, admin_user):
    fake = FakeKlarnaClient()
    _override_klarna(fake)
    order = await _create_order(db_session, admin_user.id, status=OrderStatus.AUTHORIZED)
    order.klarna_order_id = "klarna-order-1"
    await db_session.flush()

    response = await async_client.post(f"/api/v1/orders/{order.id}/capture", headers=admin_auth_headers)

    assert response.status_code == 200
    assert fake.captures == [
        (
            "klarna-order-1",
            {"captured_amount": 5000, "description": f"Capture for order {order.id}"},
        )
    ]


async def test_capture_invalid_state(async_client, admin_auth_headers, db_session, admin_user):
    order = await _create_order(db_session, admin_user.id, status=OrderStatus.PENDING)
    response = await async_client.post(f"/api/v1/orders/{order.id}/capture", headers=admin_auth_headers)
    assert response.status_code == 409


async def test_refund_success(async_client, admin_auth_headers, db_session, admin_user):
    order = await _create_order(db_session, admin_user.id, status=OrderStatus.CAPTURED)
    response = await async_client.post(f"/api/v1/orders/{order.id}/refund", headers=admin_auth_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "refunded"


async def test_cancel_success(async_client, admin_auth_headers, db_session, admin_user):
    order = await _create_order(db_session, admin_user.id, status=OrderStatus.AUTHORIZED)
    response = await async_client.post(f"/api/v1/orders/{order.id}/cancel", headers=admin_auth_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
