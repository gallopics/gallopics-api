from fastapi.routing import APIRoute

from app.main import app

UNMATCHED = "/api/v1/integrations/events/unmatched"


async def test_integrations_need_a_signed_in_user(async_client):
    response = await async_client.get(UNMATCHED)
    # Like every signed-in route here: no Authorization header is a 422
    assert response.status_code == 422


async def test_integrations_refuse_photographers(async_client, photographer_auth_headers):
    response = await async_client.post("/api/v1/integrations/equipe/sync", headers=photographer_auth_headers)
    assert response.status_code == 403


async def test_integrations_allow_admins(async_client, admin_auth_headers):
    response = await async_client.get(UNMATCHED, headers=admin_auth_headers)
    assert response.status_code == 200


def test_every_integration_route_is_admin_only():
    from tests.unit.test_db_session_scope import _api_routes

    routes = [r for r in _api_routes(app.routes) if isinstance(r, APIRoute) and r.path.startswith("/api/v1/integrations")]
    assert len(routes) == 4
    for route in routes:
        calls = [dep.call for dep in route.dependant.dependencies]
        assert any(getattr(call, "__qualname__", "").startswith("require_role") for call in calls), route.path
