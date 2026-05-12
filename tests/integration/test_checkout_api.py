from app.main import app
from app.routers.checkout import get_klarna_client


class FakeKlarnaClient:
    def __init__(self):
        self.sessions = []
        self.orders = []
        self.captures = []

    async def create_session(self, payload):
        self.sessions.append(payload)
        return {
            "session_id": "klarna-session-test",
            "client_token": "klarna-client-token-test",
            "payment_method_categories": [{"identifier": "pay_now"}],
        }

    async def create_order(self, authorization_token, payload):
        self.orders.append((authorization_token, payload))
        return {
            "order_id": "klarna-order-test",
            "fraud_status": "ACCEPTED",
        }

    async def capture(self, order_id, payload):
        self.captures.append((order_id, payload))


def _override_klarna(fake):
    async def _dependency():
        yield fake

    app.dependency_overrides[get_klarna_client] = _dependency


async def test_create_session_unauthenticated(async_client):
    fake = FakeKlarnaClient()
    _override_klarna(fake)
    response = await async_client.post("/api/v1/checkout/sessions", json={
        "line_items": [{"name": "Photo", "quantity": 1, "unit_price": 100, "total_amount": 100}],
        "idempotency_key": "key-1",
    })
    assert response.status_code == 200
    assert response.json()["session_id"] == "klarna-session-test"


async def test_create_session_authenticated(async_client, auth_headers):
    fake = FakeKlarnaClient()
    _override_klarna(fake)
    response = await async_client.post("/api/v1/checkout/sessions", json={
        "line_items": [{"name": "Photo", "quantity": 1, "unit_price": 5000, "total_amount": 5000}],
        "idempotency_key": "key-checkout-1",
    }, headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert "order_id" in data
    assert fake.sessions[0]["intent"] == "buy"
    assert fake.sessions[0]["purchase_country"] == "SE"
    assert fake.sessions[0]["order_amount"] == 5000


async def test_create_session_idempotent(async_client, auth_headers):
    fake = FakeKlarnaClient()
    _override_klarna(fake)
    body = {
        "line_items": [{"name": "Photo", "quantity": 1, "unit_price": 100, "total_amount": 100}],
        "idempotency_key": "key-idem-1",
    }
    r1 = await async_client.post("/api/v1/checkout/sessions", json=body, headers=auth_headers)
    r2 = await async_client.post("/api/v1/checkout/sessions", json=body, headers=auth_headers)
    assert r1.json()["order_id"] == r2.json()["order_id"]
    assert len(fake.sessions) == 1


async def test_authorize_success(async_client, auth_headers):
    fake = FakeKlarnaClient()
    _override_klarna(fake)
    r = await async_client.post("/api/v1/checkout/sessions", json={
        "line_items": [{"name": "Photo", "quantity": 1, "unit_price": 5000, "total_amount": 5000}],
        "idempotency_key": "key-auth-1",
    }, headers=auth_headers)
    order_id = r.json()["order_id"]

    r2 = await async_client.post("/api/v1/checkout/authorize", json={
        "order_id": order_id,
        "authorization_token": "token-123",
    }, headers=auth_headers)
    assert r2.status_code == 200
    assert r2.json()["status"] == "captured"
    assert r2.json()["klarna_order_id"] == "klarna-order-test"
    assert fake.orders[0][0] == "token-123"
    assert fake.orders[0][1]["merchant_reference1"] == order_id
    assert fake.captures == [
        (
            "klarna-order-test",
            {"captured_amount": 5000, "description": f"Capture for order {order_id}"},
        )
    ]
