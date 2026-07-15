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
RESYNC_DB = "elevator_resync_test_db"
_EXPECTED_EMPTY = ("elevators", "elevator_features", "elevator_trend_points")

# The schema-creation migration — everything before it is empty; every resync migration comes
# after it. Upgrading only this far gives us the tables with no data, so we can plant stale
# rows and then upgrade to head to prove the resync path.
_SCHEMA_ONLY_REV = "638e311fa8e1"


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
_RESYNC_ASYNC_URL = _with_db(settings.test_database_url, RESYNC_DB)
_RESYNC_DSN = _asyncpg_dsn(_RESYNC_ASYNC_URL)


def _alembic_upgrade(target: str, db_url: str) -> subprocess.CompletedProcess:
    """Run `alembic upgrade <target>` the same way the `migrate` compose service does.

    `env.py` resolves the target from `settings.database_url`, which reads `DATABASE_URL`;
    the subprocess picks it up fresh from the injected environment.
    """
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", target],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": db_url},
        capture_output=True,
        text=True,
    )


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
    result = _alembic_upgrade("head", empty_migration_db)

    assert result.returncode == 0, (
        "alembic upgrade head failed on an empty database "
        "(resync migration must be a no-op when no elevator rows exist):\n"
        f"--- STDOUT ---\n{result.stdout}\n--- STDERR ---\n{result.stderr}"
    )

    counts = _run(_table_counts(_MIGRATION_DSN))
    assert counts == {t: 0 for t in _EXPECTED_EMPTY}, (
        f"migrations must not seed data on an empty DB; got row counts: {counts}"
    )


# --- Populated-volume path: the resync migrations' original purpose --------------------------

_STALE_EID = "ELV-001"  # in-scope in predictions.json (has real risk, 3 features, 6 trend pts)
_STALE_RISK = 0.111     # sentinel: no real prediction has this exact value


async def _seed_stale_elevator(dsn: str) -> None:
    """Plant a pre-migration elevator with stale derived rows and a user-submitted report.

    Mirrors a persisted volume seeded before the resync migrations existed. Note: at
    `_SCHEMA_ONLY_REV` the `elevator_features` table has no `direction` column yet (added by a
    later migration), so the stale feature is inserted without it.
    """
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            """
            INSERT INTO elevators (
                id, building_name, building_type, floor_count, model, brand, age_years,
                risk_score, risk_level, last_visit_date, last_visit_technician,
                last_visit_notes, nl_explanation, in_model_scope, hourly_trips_avg, zone
            ) VALUES (
                $1, 'STALE Building', 'residential', 5, 'STALE-Model', 'own', 10,
                $2, 'low', '2020-01-01', 'Stale Tech', 'stale notes', 'stale explanation',
                true, 100, 'StaleZone'
            )
            """,
            _STALE_EID, _STALE_RISK,
        )
        await conn.execute(
            "INSERT INTO elevator_features (elevator_id, name, impact, value) "
            "VALUES ($1, 'STALE_FEATURE', 0.99, 'stale value')",
            _STALE_EID,
        )
        await conn.execute(
            "INSERT INTO elevator_trend_points (elevator_id, day_index, score) VALUES ($1, 0, 0.99)",
            _STALE_EID,
        )
        await conn.execute(
            "INSERT INTO visit_reports (elevator_id, technician_name, visit_date, failure_found, notes) "
            "VALUES ($1, 'Alice', '2026-07-14', true, 'REPORT_TO_PRESERVE')",
            _STALE_EID,
        )
    finally:
        await conn.close()


async def _resync_state(dsn: str) -> dict:
    conn = await asyncpg.connect(dsn)
    try:
        row = await conn.fetchrow("SELECT risk_score FROM elevators WHERE id = $1", _STALE_EID)
        feature_names = [
            r["name"] for r in await conn.fetch(
                "SELECT name FROM elevator_features WHERE elevator_id = $1", _STALE_EID
            )
        ]
        null_directions = await conn.fetchval(
            "SELECT count(*) FROM elevator_features WHERE elevator_id = $1 AND direction IS NULL",
            _STALE_EID,
        )
        trend_count = await conn.fetchval(
            "SELECT count(*) FROM elevator_trend_points WHERE elevator_id = $1", _STALE_EID
        )
        report_notes = await conn.fetchval(
            "SELECT notes FROM visit_reports WHERE elevator_id = $1", _STALE_EID
        )
        return {
            "risk_score": row["risk_score"],
            "feature_names": feature_names,
            "null_directions": null_directions,
            "trend_count": trend_count,
            "report_notes": report_notes,
        }
    finally:
        await conn.close()


@pytest.fixture
def resync_migration_db() -> str:
    """Isolated DB migrated to the schema-only revision, ready for stale rows to be planted."""
    _run(_admin_execute(f'DROP DATABASE IF EXISTS "{RESYNC_DB}" WITH (FORCE)'))
    _run(_admin_execute(f'CREATE DATABASE "{RESYNC_DB}"'))
    try:
        result = _alembic_upgrade(_SCHEMA_ONLY_REV, _RESYNC_ASYNC_URL)
        assert result.returncode == 0, (
            f"failed to build schema at {_SCHEMA_ONLY_REV}:\n{result.stderr}"
        )
        yield _RESYNC_ASYNC_URL
    finally:
        _run(_admin_execute(f'DROP DATABASE IF EXISTS "{RESYNC_DB}" WITH (FORCE)'))


def test_resync_updates_existing_rows_and_preserves_visit_reports(resync_migration_db: str) -> None:
    """On a populated volume the resync MUST still run — the guard must not over-fire.

    Guards a subtle regression: if the `rowcount` / `existing_ids` guard ever skipped rows that
    DO exist, the loud FK crash would silently become stale data. This plants a stale elevator
    (with a user-submitted visit report), upgrades to head, and asserts the resync overwrote the
    derived rows while preserving the report.
    """
    _run(_seed_stale_elevator(_RESYNC_DSN))

    result = _alembic_upgrade("head", resync_migration_db)
    assert result.returncode == 0, (
        f"alembic upgrade head failed on a populated database:\n"
        f"--- STDOUT ---\n{result.stdout}\n--- STDERR ---\n{result.stderr}"
    )

    state = _run(_resync_state(_RESYNC_DSN))
    # Scalar fields were resynced away from the stale sentinel.
    assert state["risk_score"] != _STALE_RISK, "risk_score was not resynced (guard over-fired?)"
    # Derived rows were fully replaced: the stale feature is gone, ELV-001's real 3 features and
    # 6 trend points are present, and every feature carries a non-NULL direction.
    assert "STALE_FEATURE" not in state["feature_names"], "stale feature row survived resync"
    assert len(state["feature_names"]) == 3, f"expected 3 features, got {state['feature_names']}"
    assert state["null_directions"] == 0, "a feature has a NULL direction after resync"
    assert state["trend_count"] == 6, f"expected 6 trend points, got {state['trend_count']}"
    # The user-submitted report survived (ON DELETE CASCADE must never have fired).
    assert state["report_notes"] == "REPORT_TO_PRESERVE", "visit report was lost during resync"
