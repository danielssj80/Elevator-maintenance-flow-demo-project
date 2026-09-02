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

    Narrower than its name: this reads the `environment:` block only, and the
    prod `backend` service also loads `env_file: /etc/elevator/.env`, which lives
    outside the repository and cannot be checked from here. So it asserts that
    *this file* declares no token, not that the deployed process has none.
    Harmless either way — a token would guard routes that production does not
    register — but the gap is stated rather than implied.
    """
    environment = _service_environment(PROD_COMPOSE, "backend")

    assert "TELEMETRY_INGEST_TOKEN" not in environment


def test_prod_compose_defines_no_orchestrator():
    """n8n is local-only, and that has to be checkable rather than asserted in prose.

    The orchestration tier reaches both write endpoints and holds credentials for
    a model provider. `docker-compose.prod.yml` auto-deploys on merge to the
    default branch, so an orchestrator service reaching it would put a scheduler
    with credentials on a public host — and the routers it drives are not even
    registered there.

    Named services rather than a substring search: `n8n` appears in comments and
    in image tags, and a grep would go green for the wrong reason.
    """
    compose = yaml.safe_load(PROD_COMPOSE.read_text())
    services = set(compose.get("services", {}))

    forbidden = services & {"n8n", "n8n-worker", "n8n-db-init", "redis"}
    assert not forbidden, (
        f"docker-compose.prod.yml defines {sorted(forbidden)}. The orchestration "
        "tier runs locally only: it holds a model-provider credential and drives "
        "endpoints production does not register."
    )


def test_dev_compose_keeps_the_queue_tier_behind_a_profile():
    """Queue mode is opt-in, so `docker compose up` does not cost 700 MB.

    The shape has to be there from the start though — flipping EXECUTIONS_MODE
    and enabling the profile is meant to be the whole switch, not a rewrite.
    """
    compose = yaml.safe_load(DEV_COMPOSE.read_text())
    services = compose["services"]

    for name in ("redis", "n8n-worker"):
        assert name in services, f"{name} must exist for queue mode to be one variable away"
        assert "queue" in (services[name].get("profiles") or []), (
            f"{name} must sit behind the `queue` profile so a plain `up` does not start it"
        )
    assert "profiles" not in services["n8n"], "the n8n main process is not optional"


def test_main_and_worker_share_one_encryption_key_and_otel_block():
    """A mismatch here fails every credential-using node with an opaque error.

    Both processes read the same variables with the same defaults, so they agree
    by construction — this asserts that nobody has since given one of them its
    own value. The OTel block matters for the same reason in the other
    direction: configured on main alone, the worker executes everything and
    emits nothing, which reads as the workflow never having run.
    """
    services = yaml.safe_load(DEV_COMPOSE.read_text())["services"]
    main = services["n8n"]["environment"]
    worker = services["n8n-worker"]["environment"]

    assert main["N8N_ENCRYPTION_KEY"] == worker["N8N_ENCRYPTION_KEY"]
    for key in (
        "N8N_ENABLED_MODULES",
        "N8N_OTEL_ENABLED",
        "N8N_OTEL_EXPORTER_OTLP_ENDPOINT",
        "N8N_OTEL_TRACES_PRODUCTION_ONLY",
        "N8N_AGENTS_TRACING_RECORD_INPUTS",
        "N8N_AGENTS_TRACING_RECORD_OUTPUTS",
    ):
        assert main.get(key) == worker.get(key), (
            f"{key} differs between n8n and n8n-worker; in queue mode the worker "
            "runs the executions, so a value set only on main configures nothing"
        )


def test_agent_prompt_and_output_recording_stay_off():
    """The privacy setting, asserted by VALUE rather than by agreement.

    `test_main_and_worker_share_one_encryption_key_and_otel_block` checks that
    main and worker match, which says nothing about what they match *at*.
    Flipping both to "true" kept that test green — and both default to true, so
    the whole guard is this line. n8n would then ship agent prompts and model
    output to whatever backend the Collector fans out to.
    """
    services = yaml.safe_load(DEV_COMPOSE.read_text())["services"]

    for name in ("n8n", "n8n-worker"):
        environment = services[name]["environment"]
        for key in ("N8N_AGENTS_TRACING_RECORD_INPUTS", "N8N_AGENTS_TRACING_RECORD_OUTPUTS"):
            assert environment.get(key) == "false", (
                f"{name} must set {key}=false; it defaults to TRUE, and the ops "
                "digest agent is given fleet risk data, technician names and "
                "visit notes"
            )


def test_metric_cardinality_labels_stay_off():
    """100 lifts x every workflow id is what a 10k-series budget is lost to."""
    services = yaml.safe_load(DEV_COMPOSE.read_text())["services"]

    for name in ("n8n", "n8n-worker"):
        environment = services[name]["environment"]
        for key in ("N8N_METRICS_INCLUDE_WORKFLOW_ID_LABEL",
                    "N8N_METRICS_INCLUDE_NODE_TYPE_LABEL"):
            assert environment.get(key) == "false", f"{name} must set {key}=false"


def test_dev_exports_traces_for_manual_executions():
    """`N8N_OTEL_TRACES_PRODUCTION_ONLY` defaults to true, and that default is
    the trap the orchestration docs call the nastiest in the milestone.

    Left at the default, the editor's "Test workflow" button exports zero spans,
    which is indistinguishable from tracing being broken. Asserted by value on
    both processes, because agreement between two wrong values is still wrong.
    """
    services = yaml.safe_load(DEV_COMPOSE.read_text())["services"]

    for name in ("n8n", "n8n-worker"):
        assert services[name]["environment"].get("N8N_OTEL_TRACES_PRODUCTION_ONLY") == "false"


def test_the_otel_module_is_enabled_and_tracing_is_on():
    """Both are required and neither is the default.

    OTel ships as an n8n module whose enabled list is empty by default, so
    N8N_OTEL_ENABLED on its own configures a module that was never loaded — and
    nothing is logged in either case.
    """
    services = yaml.safe_load(DEV_COMPOSE.read_text())["services"]

    for name in ("n8n", "n8n-worker"):
        environment = services[name]["environment"]
        assert "otel" in str(environment.get("N8N_ENABLED_MODULES", "")).split(",")
        assert environment.get("N8N_OTEL_ENABLED") == "true"
