import os

# The value assumed when DEPLOYMENT_ENVIRONMENT is not set anywhere.
DEFAULT_DEPLOYMENT_ENVIRONMENT = "production"

# The only names that are *not* production. Everything else is — unset, empty,
# `prod`, `Production`, `staging`, a typo. The previous rule compared against the
# one string "production", so every other spelling opened the write endpoints.
#
# Exact match, deliberately: no lower(), no strip(). Each normalisation is one
# more way for an unexpected value to land on the open side, and `Local`
# reaching the closed side costs a log line, not an incident.
NON_PRODUCTION_ENVIRONMENTS = frozenset({"local", "test", "ci"})


def is_production(environment: str) -> bool:
    """Whether ``environment`` must be treated as production."""
    return environment not in NON_PRODUCTION_ENVIRONMENTS


def _build_db_url(
    user: str = "user",
    password: str = "password",
    host: str = "localhost",
    port: str = "5432",
    db: str = "elevator_db",
) -> str:
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"


class Settings:
    database_url: str = os.getenv("DATABASE_URL") or _build_db_url(
        user=os.getenv("POSTGRES_USER", "user"),
        password=os.getenv("POSTGRES_PASSWORD", "password"),
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        db=os.getenv("POSTGRES_DB", "elevator_db"),
    )
    test_database_url: str = os.getenv(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://user:password@localhost:5432/elevator_test_db",
    )
    allowed_origins: list[str] = os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:5173,http://frontend:5173",
    ).split(",")
    bedrock_region: str = os.getenv("BEDROCK_REGION", "eu-north-1")
    bedrock_model_id: str = os.getenv("BEDROCK_MODEL_ID", "eu.amazon.nova-lite-v1:0")
    briefing_timeout_seconds: int = int(os.getenv("BRIEFING_TIMEOUT_SECONDS", "5"))

    # --- OpenTelemetry --------------------------------------------------
    # Opt-in: defaults to disabled so CI and the test suite need no Collector.
    otel_enabled: bool = os.getenv("OTEL_ENABLED", "false").lower() == "true"
    # BASE url. The SDK appends "/v1/traces" itself; passing a full path here
    # (or an explicit endpoint= to an exporter) makes it POST to the wrong URL
    # and the resulting 404 is only logged at DEBUG.
    otel_exporter_otlp_endpoint: str = os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4318"
    )
    otel_service_name: str = os.getenv("OTEL_SERVICE_NAME", "elevator-backend")
    otel_service_version: str = os.getenv("OTEL_SERVICE_VERSION", "0.1.0")
    # Fail-closed on purpose: classified by is_production(), so anything but
    # local/test/ci — including unset — is production. This value decides
    # whether the telemetry and inference routers may be registered without a
    # token. A default of "local" once meant that *forgetting* to set it
    # published them: docker-compose.prod.yml loads an out-of-repo env file, so
    # the gate was open in the one environment it exists to protect.
    #
    # Every non-production environment therefore sets it explicitly:
    # docker-compose.yml does, and tests/conftest.py does.
    deployment_environment: str = os.getenv(
        "DEPLOYMENT_ENVIRONMENT", DEFAULT_DEPLOYMENT_ENVIRONMENT
    )
    fleet_metrics_refresh_seconds: int = int(
        os.getenv("FLEET_METRICS_REFRESH_SECONDS", "60")
    )

    # --- Inference (M5 - telemetry-ingestion-inference) ---------------------
    # The scoring service is dev-only; production never has one, which is why
    # an unreachable service is a 503 rather than an error worth paging on.
    inference_url: str = os.getenv("INFERENCE_URL", "http://inference:8001")
    inference_timeout_seconds: int = int(os.getenv("INFERENCE_TIMEOUT_SECONDS", "30"))
    # When set, the backend invokes this AWS Lambda function instead of calling
    # INFERENCE_URL. Production sets it (no scoring container runs on the
    # host); local leaves it unset and keeps the HTTP service.
    inference_lambda_function: str | None = (
        os.getenv("INFERENCE_LAMBDA_FUNCTION") or None
    )
    # Readings older than this are pruned at the end of each successful run, so
    # an unattended local database stays bounded.
    telemetry_retention_days: int = int(os.getenv("TELEMETRY_RETENTION_DAYS", "30"))
    # The window an inference run aggregates over.
    inference_window_hours: int = int(os.getenv("INFERENCE_WINDOW_HOURS", "24"))

    # Shared secret for the telemetry and inference endpoints (both POSTs and
    # GET /api/telemetry/readings).
    #
    # Outside production, unset means open, so pytest and a bare `uvicorn` run
    # work with no configuration; docker-compose.yml sets one anyway (asserted
    # by tests/unit/test_dev_compose.py) and build_app warns when it registers
    # the routers unguarded. In production it is required: build_app registers
    # the routers only with a token of at least 32 characters, and
    # require_ingest_token rejects every request if it is empty. In production
    # it comes from /etc/elevator/.env, never from a committed file.
    telemetry_ingest_token: str | None = os.getenv("TELEMETRY_INGEST_TOKEN") or None


settings = Settings()
