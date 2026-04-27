import pytest
from starlette.testclient import TestClient

from app.middleware.rate_limit import RateLimitMiddleware


def test_under_limit_passes():
    from fastapi import FastAPI

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, default_rpm=5)

    @app.get("/test")
    async def test_endpoint():
        return {"ok": True}

    client = TestClient(app)
    response = client.get("/test")
    assert response.status_code == 200


def test_over_limit_returns_429():
    from fastapi import FastAPI

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, default_rpm=3)

    @app.get("/test")
    async def test_endpoint():
        return {"ok": True}

    client = TestClient(app)
    for _ in range(3):
        response = client.get("/test")
        assert response.status_code == 200

    response = client.get("/test")
    assert response.status_code == 429
    assert response.json()["detail"] == "Rate limit exceeded"
