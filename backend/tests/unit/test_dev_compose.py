"""The guards, asserted against the configuration that actually runs.

Round 3 of `telemetry-ingestion-inference` found the production gate open in the
one environment it existed to protect. It had passed every test for three
rounds, because every one of those tests set `DEPLOYMENT_ENVIRONMENT` by hand
while `docker-compose.prod.yml` set it nowhere. A guard proven in a fixture is
not proven.

So these tests read the compose files. They are the only ones in the suite that
would notice a guard that is correct in Python and absent from the deployment.
"""

import pathlib

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
DEV_COMPOSE = REPO_ROOT / "docker-compose.yml"
PROD_COMPOSE = REPO_ROOT / "docker-compose.prod.yml"


def _service_environment(compose_path: pathlib.Path, service: str) -> dict[str, str]:
    """The `environment:` block of one service, as a mapping.

    Compose accepts either a mapping or a `KEY=value` list; both are normalised
    here so the assertions do not depend on which style the file happens to use.
    """
    assert compose_path.exists(), f"{compose_path.name} is missing"
    compose = yaml.safe_load(compose_path.read_text())
    services = compose.get("services", {})
    assert service in services, f"{compose_path.name} has no `{service}` service"
    environment = services[service].get("environment") or {}
    if isinstance(environment, list):
        pairs = (entry.split("=", 1) for entry in environment)
        return {k: v for k, v in (p if len(p) == 2 else (p[0], "") for p in pairs)}
    return {k: "" if v is None else str(v) for k, v in environment.items()}


def test_dev_compose_configures_an_ingest_token():
    """The token guard is fail-open, so the development stack has to opt in.

    Without this the guard would be dead in the only environment that runs it:
    every test would pass, and every request the compose stack served would be
    unauthenticated.
    """
    environment = _service_environment(DEV_COMPOSE, "backend")

    token = environment.get("TELEMETRY_INGEST_TOKEN")
    assert token, (
        "docker-compose.yml must set TELEMETRY_INGEST_TOKEN for the backend service; "
        "the telemetry and inference routers are registered there and the guard is "
        "fail-open, so an unset token leaves them accepting unauthenticated writes"
    )


def test_dev_compose_declares_a_non_production_environment():
    """The other half: the routers must actually be registered in dev.

    A token configured on routers that were never registered would be a guard on
    nothing, and every 401 test above would still pass.
    """
    environment = _service_environment(DEV_COMPOSE, "backend")

    assert environment.get("DEPLOYMENT_ENVIRONMENT") == "local"


def test_prod_compose_declares_production_explicitly():
    """The regression guard round 3 did not have.

    `deployment_environment` defaults to "production" now, so this file being
    silent would still gate the routers off. It is asserted anyway: the default
    and the declaration are two independent reasons for the same outcome, and
    losing either one silently is how the original defect happened.

    Only `backend` — `migrate` runs `alembic upgrade head` and never builds the
    application, so requiring the variable there would be a test demanding
    configuration that guards nothing.
    """
    environment = _service_environment(PROD_COMPOSE, "backend")

    assert environment.get("DEPLOYMENT_ENVIRONMENT") == "production", (
        "docker-compose.prod.yml must set DEPLOYMENT_ENVIRONMENT=production for "
        "`backend`; that deployment auto-updates on merge to the default branch "
        "and has no authentication of any kind"
    )


def test_prod_compose_does_not_configure_an_ingest_token():
    """Nothing to configure: the routers it would guard are not registered there.

    A token in the production file would suggest those endpoints exist in
    production, which is the misreading the router gate exists to prevent.
    """
    environment = _service_environment(PROD_COMPOSE, "backend")

    assert "TELEMETRY_INGEST_TOKEN" not in environment
