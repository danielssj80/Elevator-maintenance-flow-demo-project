import os

# The value assumed when DEPLOYMENT_ENVIRONMENT is not set anywhere.
DEFAULT_DEPLOYMENT_ENVIRONMENT = "production"


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
    # Fail-closed on purpose. This value gates the telemetry and inference
    # routers, which are unauthenticated write endpoints, and the deployed API
    # has no authentication of any kind. A default of "local" meant that
    # *forgetting* to set the variable published them: docker-compose.prod.yml
    # sets it nowhere and loads an out-of-repo env file, so the gate was open in
    # the one environment it exists to protect. An unset variable must be the
    # safe answer, not the dangerous one.
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
    # Readings older than this are pruned at the end of each successful run, so
    # an unattended local database stays bounded.
    telemetry_retention_days: int = int(os.getenv("TELEMETRY_RETENTION_DAYS", "30"))
    # The window an inference run aggregates over.
    inference_window_hours: int = int(os.getenv("INFERENCE_WINDOW_HOURS", "24"))

    # Shared secret for POST /api/telemetry/readings and POST /api/inference/run.
    #
    # Unset means open, which is the opposite of `deployment_environment` above
    # and deliberately so. That one is fail-closed because forgetting it
    # publishes unauthenticated write endpoints on the internet. This one only
    # ever applies to routers that do not exist in production at all, and a
    # fail-closed default would break pytest and a bare `uvicorn` run for anyone
    # with no configuration. The safety comes from the other end instead: every
    # environment that registers those routers sets this — docker-compose.yml
    # does, and tests/unit/test_dev_compose.py asserts it against the file
    # rather than against a fixture — and build_app warns at startup when it
    # registers them unguarded.
    telemetry_ingest_token: str | None = os.getenv("TELEMETRY_INGEST_TOKEN") or None


settings = Settings()
