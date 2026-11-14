from fastapi.routing import APIRoute

from app.database import get_db
from app.main import app


def _api_routes(routes):
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        # Included routers are wrapped; their routes stay on the original router
        nested = getattr(route, "original_router", None)
        if nested is not None:
            yield from _api_routes(nested.routes)


def _db_dependency_scopes(dependant, path=()):
    for dep in dependant.dependencies:
        if dep.call is get_db:
            yield path, dep.scope
        yield from _db_dependency_scopes(dep, (*path, getattr(dep.call, "__name__", "?")))


def test_every_route_commits_before_sending_the_response():
    """With the default scope the commit runs after the response is sent: a client
    that PATCHes a just-uploaded photo right away could get a 404."""
    wrong = [
        f"{route.path} via {' > '.join(path) or 'endpoint'}: scope={scope}"
        for route in _api_routes(app.routes)
        for path, scope in _db_dependency_scopes(route.dependant)
        if scope != "function"
    ]
    assert not wrong, "Use Depends(get_db, scope=\"function\"):\n" + "\n".join(wrong)


def test_routes_are_checked():
    checked = [
        route.path
        for route in _api_routes(app.routes)
        if any(True for _ in _db_dependency_scopes(route.dependant))
    ]
    assert "/api/v1/photographer/uploads" in checked
