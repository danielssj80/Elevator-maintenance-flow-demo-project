"""The ingest and inference routers must not exist in production.

`docker-compose.prod.yml` auto-deploys on merge to the default branch, and the
deployed API has no authentication of any kind. An ungated
`POST /api/telemetry/readings` there is a public write endpoint that lets
anyone inject telemetry and re-score the live fleet.

These tests build the app through the same factory the real process uses, so a
regression in registration order or in the environment check is caught here
rather than in production.
"""

import json
import os
import pathlib
import subprocess
import sys
import textwrap

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


def test_an_unset_deployment_environment_gates_the_routes_off():
    """The guard on the guard, and it has to run in a fresh interpreter.

    Round 3 found that `docker-compose.prod.yml` sets DEPLOYMENT_ENVIRONMENT
    nowhere, so the deployed process runs with it unset. The fix made the
    default "production". Round 4 then found that reverting that default to
    "local" — literally the original bug — left the whole suite green:

      * one test asserted the *constant* equals "production", which says
        nothing about whether `os.getenv` uses it;
      * the other monkeypatched `settings.deployment_environment` **to** that
        constant, so it never exercised the environment read either.

    Both sat beside the real path. The real path is: the variable is absent
    from the environment, so `os.getenv` falls back, so `build_app()` gates.
    Only a fresh interpreter with the variable actually removed exercises it —
    this process cannot, because `conftest` sets it before anything imports and
    `Settings` reads it once at import time.
    """
    env = {k: v for k, v in os.environ.items() if k != "DEPLOYMENT_ENVIRONMENT"}

    probe = textwrap.dedent(
        """
        import json
        from app.main import build_app
        print(json.dumps(sorted(
            p for p in (getattr(r, "path", None) for r in build_app().routes) if p
        )))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        env=env,
        capture_output=True,
        text=True,
        cwd=pathlib.Path(__file__).parents[2],
    )

    assert result.returncode == 0, result.stderr
    registered = set(json.loads(result.stdout))

    for _method, path in GATED_ROUTES:
        assert path not in registered, (
            f"{path} is registered when DEPLOYMENT_ENVIRONMENT is absent from the "
            "environment — which is exactly what docker-compose.prod.yml produces"
        )
    # And the app is otherwise intact, so this is a gate and not a broken build.
    assert "/api/elevators" in registered
    assert "/health" in registered


def test_a_declared_local_environment_still_registers_them():
    """The other half: the gate must not be permanently closed."""
    env = dict(os.environ, DEPLOYMENT_ENVIRONMENT="local")

    probe = textwrap.dedent(
        """
        import json
        from app.main import build_app
        print(json.dumps(sorted(
            p for p in (getattr(r, "path", None) for r in build_app().routes) if p
        )))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        env=env,
        capture_output=True,
        text=True,
        cwd=pathlib.Path(__file__).parents[2],
    )

    assert result.returncode == 0, result.stderr
    registered = set(json.loads(result.stdout))

    for _method, path in GATED_ROUTES:
        assert path in registered
