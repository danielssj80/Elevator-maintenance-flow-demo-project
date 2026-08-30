"""The ingest and inference routers must not exist in production.

`docker-compose.prod.yml` auto-deploys on merge to the default branch, and the
deployed API has no authentication of any kind. An ungated
`POST /api/telemetry/readings` there is a public write endpoint that lets
anyone inject telemetry and re-score the live fleet.

These tests build the app through the same factory the real process uses, so a
regression in registration order or in the environment check is caught here
rather than in production.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import build_app

GATED_ROUTES = [
    ("POST", "/api/telemetry/readings"),
    ("GET", "/api/telemetry/readings"),
    ("POST", "/api/inference/run"),
]


def _paths(app) -> set[str]:
    return {getattr(r, "path", None) for r in app.routes}


def test_gated_routes_are_absent_in_production():
    app = build_app(environment="production")
    registered = _paths(app)

    for _method, path in GATED_ROUTES:
        assert path not in registered, f"{path} must not be registered in production"


@pytest.mark.asyncio
async def test_gated_routes_return_404_in_production():
    """Asserted over the wire, not just over the route table.

    ASGITransport rather than TestClient on purpose: TestClient runs the
    lifespan, which seeds the database, and this test has no business touching
    it.
    """
    app = build_app(environment="production")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/api/telemetry/readings", json={})).status_code == 404
        assert (await client.post("/api/inference/run", json={})).status_code == 404
        assert (await client.get("/health")).status_code == 200


def test_existing_routes_are_unaffected_in_production():
    app = build_app(environment="production")
    registered = _paths(app)

    assert "/health" in registered
    assert "/api/elevators" in registered
    assert "/api/elevators/{elevator_id}" in registered
    assert "/api/elevators/{elevator_id}/briefing" in registered
    assert "/api/elevators/{elevator_id}/report" in registered


@pytest.mark.parametrize("environment", ["local", "staging", "development"])
def test_gated_routes_are_present_outside_production(environment: str):
    app = build_app(environment=environment)
    registered = _paths(app)

    for _method, path in GATED_ROUTES:
        assert path in registered, f"{path} must be registered in {environment}"
