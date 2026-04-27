async def test_create_session_unauthenticated(async_client):
    response = await async_client.post("/api/v1/checkout/sessions", json={
        "line_items": [{"name": "Photo", "quantity": 1, "unit_price": 100, "total_amount": 100}],
        "idempotency_key": "key-1",
    })
    assert response.status_code in (401, 422)


async def test_create_session_authenticated(async_client, auth_headers):
    response = await async_client.post("/api/v1/checkout/sessions", json={
        "line_items": [{"name": "Photo", "quantity": 1, "unit_price": 5000, "total_amount": 5000}],
        "idempotency_key": "key-checkout-1",
    }, headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert "order_id" in data


async def test_create_session_idempotent(async_client, auth_headers):
    body = {
        "line_items": [{"name": "Photo", "quantity": 1, "unit_price": 100, "total_amount": 100}],
        "idempotency_key": "key-idem-1",
    }
    r1 = await async_client.post("/api/v1/checkout/sessions", json=body, headers=auth_headers)
    r2 = await async_client.post("/api/v1/checkout/sessions", json=body, headers=auth_headers)
    assert r1.json()["order_id"] == r2.json()["order_id"]


async def test_authorize_success(async_client, auth_headers):
    # Create session first
    r = await async_client.post("/api/v1/checkout/sessions", json={
        "line_items": [{"name": "Photo", "quantity": 1, "unit_price": 5000, "total_amount": 5000}],
        "idempotency_key": "key-auth-1",
    }, headers=auth_headers)
    order_id = r.json()["order_id"]

    # Authorize
    r2 = await async_client.post("/api/v1/checkout/authorize", json={
        "order_id": order_id,
        "authorization_token": "token-123",
    }, headers=auth_headers)
    assert r2.status_code == 200
    assert r2.json()["status"] == "authorized"
