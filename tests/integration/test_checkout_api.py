from app.main import app
from app.models.enums import PhotographerStatus, PhotoStatus, PhotoVisibility, UserRole
from app.models.event import Event
from app.models.photographer import Photo, Photographer
from app.models.user import User
from app.routers.checkout import get_klarna_client
from tests.factories import make_event


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


async def test_authorize_creates_photo_purchase(async_client, db_session):
    fake = FakeKlarnaClient()
    _override_klarna(fake)

    photographer_user = User(
        clerk_user_id="clerk_purchase_photo",
        email="purchase-photo@example.com",
        role=UserRole.PHOTOGRAPHER,
    )
    db_session.add(photographer_user)
    await db_session.flush()
    photographer = Photographer(
        user_id=photographer_user.id,
        slug="purchase-photo",
        display_name="Purchase Photo",
        status=PhotographerStatus.APPROVED,
    )
    db_session.add(photographer)
    event = Event(**make_event(name="Purchase Event"))
    db_session.add(event)
    await db_session.flush()
    photo = Photo(
        event_id=event.id,
        photographer_id=photographer.id,
        storage_key_original="originals/purchase.jpg",
        price=5000,
        status=PhotoStatus.READY,
        visibility=PhotoVisibility.PUBLISHED,
    )
    db_session.add(photo)
    await db_session.flush()

    session_response = await async_client.post(
        "/api/v1/checkout/sessions",
        json={
            "line_items": [
                {
                    "name": "Photo",
                    "quantity": 1,
                    "unit_price": 5000,
                    "total_amount": 5000,
                    "photo_id": str(photo.id),
                    "quality": "high",
                }
            ],
            "idempotency_key": "key-photo-purchase",
        },
    )
    order_id = session_response.json()["order_id"]

    authorize_response = await async_client.post(
        "/api/v1/checkout/authorize",
        json={"order_id": order_id, "authorization_token": "token-photo"},
    )

    assert authorize_response.status_code == 200
    download_response = await async_client.post(
        f"/api/v1/photos/{photo.id}/download",
        json={"order_id": order_id},
    )
    assert download_response.status_code == 200
    assert "originals/purchase.jpg" in download_response.json()["url"]
