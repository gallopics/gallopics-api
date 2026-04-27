async def test_get_profile_unauthenticated(async_client):
    response = await async_client.get("/api/v1/me")
    assert response.status_code in (401, 422)


async def test_get_profile_authenticated(async_client, auth_headers):
    response = await async_client.get("/api/v1/me", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "test@example.com"


async def test_get_my_orders_empty(async_client, auth_headers):
    response = await async_client.get("/api/v1/me/orders", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []
