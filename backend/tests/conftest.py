import asyncio
import os
from collections.abc import AsyncGenerator

# Before any app import. `deployment_environment` is fail-closed — it defaults
# to "production", which gates the telemetry and inference routers off — so the
# suite has to say what it is. Setting it here rather than in the pytest command
# means the declaration lives with the tests instead of in whatever shell or CI
# job happens to invoke them.
os.environ.setdefault("DEPLOYMENT_ENVIRONMENT", "local")

# The suite runs with the ingest guard **open**, declared rather than inherited.
# `telemetry_ingest_token` is fail-open, so most tests post to the write
# endpoints with no header and expect that to work. A developer with
# TELEMETRY_INGEST_TOKEN exported in their shell would otherwise get a suite full
# of unexplained 401s that CI does not reproduce — the same class of divergence
# between "green here" and "green in CI" that DEPLOYMENT_ENVIRONMENT is pinned
# for above. `tests/unit/test_ingest_auth.py` configures a token per test where
# it needs one.
os.environ.pop("TELEMETRY_INGEST_TOKEN", None)

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.database import Base, get_db
from app.main import app

test_engine = create_async_engine(settings.test_database_url, echo=False)
TestSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Force all async tests to use the session event loop (required by asyncpg)."""
    session_scope = pytest.mark.asyncio(loop_scope="session")
    for item in items:
        if isinstance(item, pytest.Function) and asyncio.iscoroutinefunction(item.function):
            item.add_marker(session_scope, append=False)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_test_db():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


@pytest_asyncio.fixture
async def db_session(setup_test_db) -> AsyncGenerator[AsyncSession, None]:
    async with TestSessionLocal() as session:
        yield session
        await session.rollback()


@pytest.fixture(autouse=True)
def _clear_briefing_cache():
    """Reset the process-local briefing cache between tests.

    `briefing_service._CACHE` is a module-level dict, so it leaks across test
    modules, not just across tests in one file. Living here rather than in
    test_briefing_service.py means a new test file cannot silently inherit a
    cached briefing and assert against the wrong source.
    """
    from app.services import briefing_service

    briefing_service._CACHE.clear()
    yield
    briefing_service._CACHE.clear()


@pytest.fixture(scope="session", autouse=True)
def _telemetry_session():
    """Configure telemetry once per session with in-memory exporters.

    Session-scoped on purpose: ``trace.set_tracer_provider`` only takes effect
    the first time it is called in a process, so configuring per test would
    leave later tests writing into the first provider's exporter.

    ``enabled=True`` is passed explicitly rather than mutating
    ``settings.otel_enabled``, so the settings singleton keeps its real default
    and the opt-in tests stay meaningful.
    """
    from opentelemetry.sdk._logs.export import (
        InMemoryLogExporter,
        SimpleLogRecordProcessor,
    )
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    from app.core import telemetry as telemetry_module

    exporter = InMemorySpanExporter()
    reader = InMemoryMetricReader()
    # In-memory for logs too. Without this the suite opens a real OTLP
    # connection and publishes its own log records under the production service
    # name — test traffic became indistinguishable from real traffic in Loki.
    log_exporter = InMemoryLogExporter()
    telemetry_module.configure_telemetry(
        app,
        enabled=True,
        span_exporter=exporter,
        metric_reader=reader,
        log_record_processor=SimpleLogRecordProcessor(log_exporter),
        db_engine=test_engine,
    )
    # Starlette caches its middleware stack on the first request. Instrumenting
    # afterwards would add middleware that never runs, so force a rebuild.
    # Autouse + session scope means this happens before any test makes a
    # request; in production the same ordering is guaranteed because
    # configure_telemetry() runs at import time in main.py.
    app.middleware_stack = None
    yield exporter, reader, log_exporter
    telemetry_module._uninstrument_for_tests(app)
    app.middleware_stack = None


@pytest.fixture
def metric_reader(_telemetry_session):
    """The in-memory metric reader, for collecting real instrument output.

    Asserting on callback functions directly proves nothing about whether the
    instruments are wired to a provider at all.
    """
    _, reader, _ = _telemetry_session
    return reader


@pytest.fixture
def log_exporter(_telemetry_session):
    """The in-memory log exporter, for proving the log pipeline is wired."""
    _, _, exporter = _telemetry_session
    return exporter


@pytest.fixture
def span_exporter(_telemetry_session):
    """A cleared in-memory span exporter for a single test."""
    exporter, _, _ = _telemetry_session
    exporter.clear()
    return exporter


@pytest_asyncio.fixture
async def traced_client(
    span_exporter, db_session: AsyncSession
) -> AsyncGenerator[AsyncClient, None]:
    """Client hitting the instrumented app, backed by the instrumented engine."""

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
