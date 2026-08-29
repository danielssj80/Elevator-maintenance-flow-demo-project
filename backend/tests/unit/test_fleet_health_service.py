"""Tests for the fleet-health snapshot and its metric instruments."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.core import metrics as metrics_module
from app.core.metrics import FleetHealthSnapshot
from app.services.fleet_health_service import FleetHealthService


def _elevator(risk_score: float, *, in_model_scope: bool = True):
    """Minimal stand-in carrying only what the snapshot reads."""

    class _E:
        pass

    e = _E()
    e.risk_score = risk_score
    e.in_model_scope = in_model_scope
    return e


def _service(elevators: list) -> FleetHealthService:
    repo = AsyncMock()
    repo.list_all.return_value = elevators
    return FleetHealthService(repo)


class TestComputeSnapshot:
    async def test_counts_elevators_by_derived_risk_level(self) -> None:
        service = _service(
            [
                _elevator(0.95),  # high  (> 0.80)
                _elevator(0.85),  # high
                _elevator(0.60),  # medium (0.50 - 0.80)
                _elevator(0.50),  # medium, boundary
                _elevator(0.20),  # low
            ]
        )

        snapshot = await service.compute_snapshot()

        assert snapshot.counts_by_risk_level == {
            "high": 2,
            "medium": 2,
            "low": 1,
            "out_of_scope": 0,
        }

    async def test_out_of_scope_elevators_are_counted_separately(self) -> None:
        """They are never scored, so bucketing them as `low` would be a lie."""
        service = _service(
            [
                _elevator(0.95),
                _elevator(0.0, in_model_scope=False),
                _elevator(0.0, in_model_scope=False),
            ]
        )

        snapshot = await service.compute_snapshot()

        assert snapshot.counts_by_risk_level["out_of_scope"] == 2
        assert snapshot.counts_by_risk_level["low"] == 0

    async def test_counts_sum_to_the_fleet_size(self) -> None:
        elevators = [_elevator(s) for s in (0.9, 0.7, 0.4, 0.1)] + [
            _elevator(0.0, in_model_scope=False)
        ]
        service = _service(elevators)

        snapshot = await service.compute_snapshot()

        assert sum(snapshot.counts_by_risk_level.values()) == len(elevators)

    async def test_empty_fleet_produces_zero_counts_not_an_error(self) -> None:
        snapshot = await _service([]).compute_snapshot()

        assert snapshot.counts_by_risk_level == {
            "high": 0,
            "medium": 0,
            "low": 0,
            "out_of_scope": 0,
        }

    async def test_inference_and_telemetry_fields_are_unknown_for_now(self) -> None:
        """Both are populated by the telemetry-ingestion change, not this one."""
        snapshot = await _service([_elevator(0.5)]).compute_snapshot()

        assert snapshot.last_inference_run_at is None
        assert snapshot.stale_telemetry_count is None

    async def test_snapshot_records_when_it_was_captured(self) -> None:
        before = datetime.now(UTC)
        snapshot = await _service([]).compute_snapshot()
        assert before <= snapshot.captured_at <= datetime.now(UTC)


class TestSnapshotState:
    def test_the_snapshot_is_immutable(self) -> None:
        """Callbacks read it from an exporter thread; rebinding must be atomic."""
        snapshot = metrics_module.get_snapshot()
        with pytest.raises(Exception):
            snapshot.counts_by_risk_level = {}  # type: ignore[misc]

    def test_setting_a_snapshot_replaces_the_previous_one(self) -> None:
        original = metrics_module.get_snapshot()
        try:
            new = replace(original, counts_by_risk_level={"high": 7})
            metrics_module.set_snapshot(new)
            assert metrics_module.get_snapshot().counts_by_risk_level == {"high": 7}
        finally:
            metrics_module.set_snapshot(original)


class TestMetricCallbacks:
    def test_fleet_count_is_reported_once_per_risk_level(self) -> None:
        original = metrics_module.get_snapshot()
        try:
            metrics_module.set_snapshot(
                replace(
                    original,
                    counts_by_risk_level={
                        "high": 3,
                        "medium": 5,
                        "low": 90,
                        "out_of_scope": 2,
                    },
                )
            )
            observations = list(metrics_module._observe_fleet_count(None))

            assert len(observations) == 4
            assert {o.attributes["risk_level"] for o in observations} == {
                "high",
                "medium",
                "low",
                "out_of_scope",
            }
            assert sum(o.value for o in observations) == 100
        finally:
            metrics_module.set_snapshot(original)

    def test_no_observation_carries_an_elevator_id(self) -> None:
        """Cardinality guard: 100 elevators would be 400 series."""
        observations = list(metrics_module._observe_fleet_count(None))
        for o in observations:
            assert "elevator.id" not in o.attributes
            assert "elevator_id" not in o.attributes

    def test_inference_age_reports_nothing_when_no_run_has_happened(self) -> None:
        original = metrics_module.get_snapshot()
        try:
            metrics_module.set_snapshot(replace(original, last_inference_run_at=None))
            assert list(metrics_module._observe_inference_age(None)) == []
        finally:
            metrics_module.set_snapshot(original)

    def test_inference_age_reports_seconds_since_the_last_run(self) -> None:
        original = metrics_module.get_snapshot()
        try:
            ran_at = datetime.now(UTC) - timedelta(hours=2)
            metrics_module.set_snapshot(replace(original, last_inference_run_at=ran_at))
            observations = list(metrics_module._observe_inference_age(None))

            assert len(observations) == 1
            assert 7150 <= observations[0].value <= 7250
        finally:
            metrics_module.set_snapshot(original)

    def test_stale_telemetry_reports_nothing_while_unknown(self) -> None:
        original = metrics_module.get_snapshot()
        try:
            metrics_module.set_snapshot(replace(original, stale_telemetry_count=None))
            assert list(metrics_module._observe_stale_telemetry(None)) == []
        finally:
            metrics_module.set_snapshot(original)


class TestRefreshLoop:
    async def test_refresh_failure_keeps_the_previous_snapshot(self) -> None:
        """A database blip must not blank the dashboard."""
        original = metrics_module.get_snapshot()
        try:
            known_good = replace(original, counts_by_risk_level={"high": 1})
            metrics_module.set_snapshot(known_good)

            failing = AsyncMock()
            failing.compute_snapshot.side_effect = RuntimeError("db unreachable")

            await metrics_module.refresh_snapshot_once(failing)

            assert metrics_module.get_snapshot() is known_good
        finally:
            metrics_module.set_snapshot(original)

    async def test_successful_refresh_replaces_the_snapshot(self) -> None:
        original = metrics_module.get_snapshot()
        try:
            fresh = FleetHealthSnapshot(
                counts_by_risk_level={"high": 9, "medium": 0, "low": 0, "out_of_scope": 0},
                last_inference_run_at=None,
                stale_telemetry_count=None,
                captured_at=datetime.now(UTC),
            )
            service = AsyncMock()
            service.compute_snapshot.return_value = fresh

            await metrics_module.refresh_snapshot_once(service)

            assert metrics_module.get_snapshot() is fresh
        finally:
            metrics_module.set_snapshot(original)


class TestLifespanRefreshTask:
    async def test_task_refreshes_then_stops_cleanly_on_cancellation(self) -> None:
        """The loop must survive being cancelled without leaking an error."""
        original = metrics_module.get_snapshot()
        try:
            metrics_module.set_snapshot(
                replace(original, counts_by_risk_level={"high": 0})
            )

            import asyncio
            import contextlib

            from tests.conftest import TestSessionLocal

            task = asyncio.create_task(
                metrics_module.refresh_snapshot_periodically(TestSessionLocal, 60)
            )
            # Let one cycle run against the real (empty) test database.
            await asyncio.sleep(0.2)
            assert metrics_module.get_snapshot().counts_by_risk_level == {
                "high": 0,
                "medium": 0,
                "low": 0,
                "out_of_scope": 0,
            }

            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            assert task.cancelled() or task.done()
        finally:
            metrics_module.set_snapshot(original)


class TestInstrumentRegistration:
    def test_registering_instruments_creates_the_counters(self) -> None:
        metrics_module.register_instruments()

        assert metrics_module.briefing_requests is not None
        assert metrics_module.inference_runs is not None
        assert metrics_module.inference_duration is not None

    def test_registering_twice_is_a_no_op(self) -> None:
        """Repeated application startups in one process must not duplicate."""
        metrics_module.register_instruments()
        first = metrics_module.briefing_requests

        metrics_module.register_instruments()

        assert metrics_module.briefing_requests is first

    def test_recording_a_briefing_before_registration_is_silent(self) -> None:
        """Telemetry is opt-in, so service code must not blow up when it is off."""
        saved = metrics_module.briefing_requests
        try:
            metrics_module.briefing_requests = None
            metrics_module.record_briefing_request(source="bedrock", cache_hit=False)
        finally:
            metrics_module.briefing_requests = saved

    def test_recording_a_briefing_after_registration_does_not_raise(self) -> None:
        metrics_module.register_instruments()
        metrics_module.record_briefing_request(source="fallback", cache_hit=True)


class TestRefreshLoopResilience:
    async def test_loop_survives_a_failing_session_factory(self) -> None:
        """A broken database connection must not kill the only scheduler."""
        import asyncio
        import contextlib

        original = metrics_module.get_snapshot()
        try:
            def _broken_factory():
                raise RuntimeError("connection pool exhausted")

            task = asyncio.create_task(
                metrics_module.refresh_snapshot_periodically(_broken_factory, 0.05)
            )
            await asyncio.sleep(0.2)

            assert not task.done(), "the refresh loop died on a database error"
            assert metrics_module.get_snapshot() is original

            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        finally:
            metrics_module.set_snapshot(original)
