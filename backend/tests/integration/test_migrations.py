"""Integration test: the Alembic migration chain must succeed against an empty database.

Reproduces and guards the regression where the resync migration
``0aac4958720e_resync_elevators_from_predictions_json`` inserted
``elevator_features`` / ``elevator_trend_points`` rows without a parent ``elevators`` row,
violating the ``elevator_features_elevator_id_fkey`` foreign key on any fresh/empty
database. That broke the ``migrate`` compose service on a clean stack startup
(``database-infrastructure`` spec, "Clean stack startup" scenario).

This runs the *real* ``alembic upgrade head`` against an isolated, freshly created
database — the same code path the ``migrate`` service uses — which the rest of the suite
never exercises (``conftest.py`` builds the schema with ``Base.metadata.create_all``).

Migrations MUST be a no-op on data against an empty database: seeding the fleet is
``seed_database()``'s job at backend startup, never a migration's.
"""
import asyncio
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest

from app.core.config import settings

# backend/tests/integration/test_migrations.py -> parents[2] == backend/ (holds alembic.ini)
BACKEND_DIR = Path(__file__).resolve().parents[2]
MIGRATION_DB = "elevator_migration_test_db"
_EXPECTED_EMPTY = ("elevators", "elevator_features", "elevator_trend_points")


def _with_db(async_url: str, dbname: str) -> str:
    """Return ``async_url`` with its database name replaced by ``dbname``."""
    return urlunsplit(urlsplit(async_url)._replace(path=f"/{dbname}"))


def _asyncpg_dsn(async_url: str) -> str:
    """Strip the ``+asyncpg`` SQLAlchemy driver tag so ``asyncpg.connect`` accepts the DSN."""
    return async_url.replace("+asyncpg", "")


# Derive every URL from the configured test database so host/credentials follow the
# environment (localhost locally, the ``db`` service inside the compose network).
_ADMIN_DSN = _asyncpg_dsn(_with_db(settings.test_database_url, "postgres"))
_MIGRATION_ASYNC_URL = _with_db(settings.test_database_url, MIGRATION_DB)
_MIGRATION_DSN = _asyncpg_dsn(_MIGRATION_ASYNC_URL)


def _run(coro):
    """Run ``coro`` on a private event loop, leaving asyncio's global state untouched.

    This test is synchronous, but its DB admin/count helpers are async (asyncpg). Using
    ``asyncio.run`` here would call ``set_event_loop(None)`` on teardown and break the
    session-scoped loop that pytest-asyncio shares with the async tests. A private loop that
    we never register globally avoids that.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _admin_execute(sql: str) -> None:
    conn = await asyncpg.connect(_ADMIN_DSN)
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


async def _table_counts(dsn: str) -> dict[str, int]:
    conn = await asyncpg.connect(dsn)
    try:
        return {t: await conn.fetchval(f"SELECT count(*) FROM {t}") for t in _EXPECTED_EMPTY}
    finally:
        await conn.close()


@pytest.fixture
def empty_migration_db() -> str:
    """Create a pristine, empty database for a single migration run; drop it afterwards.

    Isolated from the shared ``elevator_test_db`` (which the session-scoped ``setup_test_db``
    fixture fills via ``create_all``) so the migration chain runs against a genuinely empty DB
    without disturbing the rest of the suite. A plain sync fixture: it drives asyncpg through
    ``_run`` (a private event loop) and never touches the pytest-asyncio session loop.
    """
    _run(_admin_execute(f'DROP DATABASE IF EXISTS "{MIGRATION_DB}" WITH (FORCE)'))
    _run(_admin_execute(f'CREATE DATABASE "{MIGRATION_DB}"'))
    try:
        yield _MIGRATION_ASYNC_URL
    finally:
        _run(_admin_execute(f'DROP DATABASE IF EXISTS "{MIGRATION_DB}" WITH (FORCE)'))


def test_alembic_upgrade_head_succeeds_on_empty_db(empty_migration_db: str) -> None:
    """`alembic upgrade head` must complete on an empty DB and leave data tables empty."""
    env = {**os.environ, "DATABASE_URL": empty_migration_db}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        "alembic upgrade head failed on an empty database "
        "(resync migration must be a no-op when no elevator rows exist):\n"
        f"--- STDOUT ---\n{result.stdout}\n--- STDERR ---\n{result.stderr}"
    )

    counts = _run(_table_counts(_MIGRATION_DSN))
    assert counts == {t: 0 for t in _EXPECTED_EMPTY}, (
        f"migrations must not seed data on an empty DB; got row counts: {counts}"
    )
