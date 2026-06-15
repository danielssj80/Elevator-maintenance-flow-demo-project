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


settings = Settings()
