import os


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
    deployment_environment: str = os.getenv("DEPLOYMENT_ENVIRONMENT", "local")
    fleet_metrics_refresh_seconds: int = int(
        os.getenv("FLEET_METRICS_REFRESH_SECONDS", "60")
    )


settings = Settings()
