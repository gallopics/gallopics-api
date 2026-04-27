async def test_health_returns_200(async_client):
    response = await async_client.get("/health")
    assert response.status_code == 200


async def test_health_response_schema(async_client):
    response = await async_client.get("/health")
    data = response.json()
    assert "status" in data
    assert "version" in data
    assert data["status"] == "ok"


async def test_health_contains_version(async_client):
    response = await async_client.get("/health")
    data = response.json()
    assert data["version"] == "1.0.0"


async def test_database_health_returns_200(async_client):
    response = await async_client.get("/health/db")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
