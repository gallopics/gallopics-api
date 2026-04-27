import uuid

from app.models.enums import MatchStatus, OrderStatus
from app.models.event import Event
from app.models.order import Order
from tests.factories import make_event


async def _seed_event(db_session, **overrides):
    data = make_event(**overrides)
    event = Event(**data)
    db_session.add(event)
    await db_session.flush()
    return event


async def test_admin_endpoints_require_auth(async_client):
    response = await async_client.get("/api/v1/admin/orders")
    assert response.status_code in (401, 422)


async def test_admin_endpoints_require_admin_role(async_client, auth_headers):
    response = await async_client.get("/api/v1/admin/orders", headers=auth_headers)
    assert response.status_code == 403


async def test_list_all_orders(async_client, admin_auth_headers, db_session, admin_user):
    order = Order(user_id=admin_user.id, amount=5000, currency="SEK", status=OrderStatus.PENDING)
    db_session.add(order)
    await db_session.flush()

    response = await async_client.get("/api/v1/admin/orders", headers=admin_auth_headers)
    assert response.status_code == 200
    assert response.json()["total"] >= 1


async def test_list_orders_filter_by_status(async_client, admin_auth_headers, db_session, admin_user):
    o1 = Order(user_id=admin_user.id, amount=1000, currency="SEK", status=OrderStatus.PENDING)
    o2 = Order(user_id=admin_user.id, amount=2000, currency="SEK", status=OrderStatus.CAPTURED)
    db_session.add_all([o1, o2])
    await db_session.flush()

    response = await async_client.get(
        "/api/v1/admin/orders?status=captured", headers=admin_auth_headers
    )
    data = response.json()
    assert all(o["status"] == "captured" for o in data["items"])


async def test_manual_match_success(async_client, admin_auth_headers, db_session):
    event = await _seed_event(db_session, name="Test Match Event")
    response = await async_client.post(
        f"/api/v1/admin/events/{event.id}/match",
        json={"equipe_id": "equipe-manual-1"},
        headers=admin_auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["match_status"] == "manual"


async def test_manual_match_event_not_found(async_client, admin_auth_headers):
    response = await async_client.post(
        f"/api/v1/admin/events/{uuid.uuid4()}/match",
        json={"equipe_id": "eq-1"},
        headers=admin_auth_headers,
    )
    assert response.status_code == 404


async def test_unmatch_success(async_client, admin_auth_headers, db_session):
    event = await _seed_event(db_session, name="Matched Event")
    # First match it
    await async_client.post(
        f"/api/v1/admin/events/{event.id}/match",
        json={"equipe_id": "eq-2"},
        headers=admin_auth_headers,
    )
    # Then unmatch
    response = await async_client.post(
        f"/api/v1/admin/events/{event.id}/unmatch",
        headers=admin_auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["match_status"] == "unmatched"
