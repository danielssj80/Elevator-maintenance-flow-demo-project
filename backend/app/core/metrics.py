"""Fleet-health metric instruments and the snapshot they read.

Why a snapshot rather than a query in the callback: the metric reader invokes
observable-gauge callbacks on its own background thread, where there is no
event loop and an ``AsyncSession`` cannot be awaited. Bouncing back to the main
loop with ``run_coroutine_threadsafe`` deadlocks precisely when that loop is
blocked, which is the situation worth measuring. So an async task owned by the
application lifespan recomputes an immutable snapshot on an interval, and the
callbacks only read the current one.

Rebinding a frozen dataclass is atomic, so no lock is needed.

Cardinality: ``elevator.id`` must never appear as a metric attribute. One
hundred elevators across four risk levels would be four hundred series against
a ten-thousand-series budget.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from opentelemetry import metrics as otel_metrics
from opentelemetry.metrics import CallbackOptions, Observation

if TYPE_CHECKING:
    from app.services.fleet_health_service import FleetHealthService

logger = logging.getLogger(__name__)

RISK_LEVELS = ("high", "medium", "low", "out_of_scope")


def _empty_counts() -> dict[str, int]:
    return dict.fromkeys(RISK_LEVELS, 0)


@dataclass(frozen=True)
class FleetHealthSnapshot:
    """An immutable point-in-time view of fleet state.

    ``last_inference_run_at`` and ``stale_telemetry_count`` are ``None`` until
    the telemetry-ingestion change lands. They are deliberately reported as
    absent rather than as zero: "no inference has ever run" and "zero elevators
    are stale" mean opposite things on a dashboard.
    """

    counts_by_risk_level: dict[str, int] = field(default_factory=_empty_counts)
    last_inference_run_at: datetime | None = None
    stale_telemetry_count: int | None = None
    captured_at: datetime = field(default_factory=lambda: datetime.now(UTC))


_snapshot: FleetHealthSnapshot = FleetHealthSnapshot()


def get_snapshot() -> FleetHealthSnapshot:
    return _snapshot


def set_snapshot(snapshot: FleetHealthSnapshot) -> None:
    global _snapshot
    _snapshot = snapshot


# --- observable gauge callbacks -------------------------------------------
# Each reads only the module-level snapshot: no I/O, no awaiting, safe to run
# on the metric reader's thread.


def _observe_fleet_count(options: CallbackOptions | None) -> Iterable[Observation]:
    counts = _snapshot.counts_by_risk_level
    for level in RISK_LEVELS:
        yield Observation(counts.get(level, 0), {"risk_level": level})


def _observe_inference_age(options: CallbackOptions | None) -> Iterable[Observation]:
    ran_at = _snapshot.last_inference_run_at
    if ran_at is None:
        return
    yield Observation((datetime.now(UTC) - ran_at).total_seconds())


def _observe_stale_telemetry(options: CallbackOptions | None) -> Iterable[Observation]:
    count = _snapshot.stale_telemetry_count
    if count is None:
        return
    yield Observation(count)


# --- instruments -----------------------------------------------------------

_instruments_registered = False
briefing_requests: Any = None
inference_runs: Any = None
inference_duration: Any = None


def register_instruments() -> None:
    """Create the instruments against the configured MeterProvider.

    Called after ``configure_telemetry``; a no-op if already done, so repeated
    application startups in one process cannot register duplicates.
    """
    global _instruments_registered, briefing_requests, inference_runs, inference_duration

    if _instruments_registered:
        return

    meter = otel_metrics.get_meter(__name__)

    meter.create_observable_gauge(
        "elevator.fleet.count",
        callbacks=[_observe_fleet_count],
        unit="{elevator}",
        description="Elevators in the fleet, by derived risk level",
    )
    meter.create_observable_gauge(
        "elevator.inference.last_run.age",
        callbacks=[_observe_inference_age],
        unit="s",
        description="Seconds since the last successful inference run",
    )
    meter.create_observable_gauge(
        "elevator.telemetry.stale.count",
        callbacks=[_observe_stale_telemetry],
        unit="{elevator}",
        description="Elevators with no telemetry reading in the last 24 hours",
    )

    briefing_requests = meter.create_counter(
        "elevator.briefing.requests",
        unit="{request}",
        description="Briefing requests, by source and cache outcome",
    )
    inference_runs = meter.create_counter(
        "elevator.inference.runs",
        unit="{run}",
        description="Inference runs, by outcome",
    )
    inference_duration = meter.create_histogram(
        "elevator.inference.duration",
        unit="s",
        description="Duration of an inference run",
    )

    _instruments_registered = True


def record_briefing_request(*, source: str, cache_hit: bool) -> None:
    """Increment the briefing counter. Safe when instruments are not registered."""
    if briefing_requests is None:
        return
    briefing_requests.add(1, {"source": source, "cache": "hit" if cache_hit else "miss"})


# --- refresh loop ----------------------------------------------------------


async def refresh_snapshot_once(service: FleetHealthService) -> None:
    """Recompute the snapshot, keeping the previous one if the attempt fails.

    A database blip must degrade to a stale dashboard, not a blank one.
    """
    try:
        set_snapshot(await service.compute_snapshot())
    except Exception:
        logger.warning("Fleet-health snapshot refresh failed; keeping previous", exc_info=True)


async def refresh_snapshot_periodically(
    session_factory: Any, interval_seconds: int
) -> None:
    """Refresh forever until cancelled. Owned by the application lifespan.

    This loop is the application's only scheduler. Saying so plainly is better
    than pretending the metrics appear by themselves.
    """
    from app.repositories.elevator_repository import ElevatorRepository
    from app.services.fleet_health_service import FleetHealthService

    while True:
        try:
            async with session_factory() as session:
                await refresh_snapshot_once(FleetHealthService(ElevatorRepository(session)))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Fleet-health refresh cycle failed", exc_info=True)
        await asyncio.sleep(interval_seconds)
