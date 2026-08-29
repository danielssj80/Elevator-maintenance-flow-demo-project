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


def _collect(reader, metric_name):
    """Pull metrics through the real reader and return matching data points."""
    data = reader.get_metrics_data()
    points = []
    for rm in data.resource_metrics:
        for sm in rm.scope_metrics:
            for metric in sm.metrics:
                if metric.name == metric_name:
                    points.extend(metric.data.data_points)
    return points


class TestMetricsAreActuallyWired:
    """Collects through the reader instead of calling callbacks directly.

    Calling `_observe_fleet_count(None)` proves the function works; it proves
    nothing about whether the instrument was ever registered against a
    provider. Removing `callbacks=[...]`, removing `register_instruments()`
    from the lifespan, or deleting the `record_briefing_request` calls all left
    the previous tests green.
    """

    def test_fleet_count_is_emitted_through_the_reader(self, metric_reader) -> None:
        metrics_module.register_instruments()
        original = metrics_module.get_snapshot()
        try:
            metrics_module.set_snapshot(
                replace(
                    original,
                    counts_by_risk_level={
                        "high": 3, "medium": 5, "low": 90, "out_of_scope": 2
                    },
                )
            )
            points = _collect(metric_reader, "elevator.fleet.count")

            assert points, "elevator.fleet.count emitted nothing — is the gauge registered?"
            by_level = {p.attributes["risk_level"]: p.value for p in points}
            assert by_level == {"high": 3, "medium": 5, "low": 90, "out_of_scope": 2}
        finally:
            metrics_module.set_snapshot(original)

    def test_no_emitted_metric_carries_an_elevator_id(self, metric_reader) -> None:
        metrics_module.register_instruments()
        data = metric_reader.get_metrics_data()
        for rm in data.resource_metrics:
            for sm in rm.scope_metrics:
                for metric in sm.metrics:
                    for point in metric.data.data_points:
                        keys = set(point.attributes or {})
                        assert not keys & {"elevator.id", "elevator_id"}, (
                            f"{metric.name} carries an elevator id — "
                            "100 elevators would explode the series count"
                        )

    async def test_serving_a_briefing_increments_the_counter(
        self, metric_reader
    ) -> None:
        """Goes through the SERVICE, not through record_briefing_request.

        Calling the recorder directly still passes when the service stops
        calling it, which is the mutation that matters: the genai dashboard's
        fallback rate and cache-hit ratio would both go permanently empty.
        """
        from unittest.mock import AsyncMock, MagicMock

        from tests.unit.test_briefing_service import _make_orm_elevator

        from app.services.briefing_service import BriefingService

        metrics_module.register_instruments()

        def _count(points):
            return sum(
                p.value for p in points
                if p.attributes.get("source") == "fallback"
            )

        before = _count(_collect(metric_reader, "elevator.briefing.requests"))

        repo = AsyncMock()
        repo.get_by_id.return_value = _make_orm_elevator(id="ELV-901")
        client = MagicMock()
        client.generate.side_effect = RuntimeError("bedrock down")
        await BriefingService(
            elevator_repository=repo, bedrock_client=client
        ).get_briefing("ELV-901")

        after = _count(_collect(metric_reader, "elevator.briefing.requests"))
        assert after == before + 1, (
            "serving a fallback briefing did not increment "
            "elevator.briefing.requests — the service is not recording it"
        )


class TestLifespanWiring:
    async def test_lifespan_registers_instruments_and_manages_the_refresh_task(
        self, monkeypatch, metric_reader
    ) -> None:
        """Drives the real lifespan.

        The refresh task was previously only tested against a task the test
        built itself, so removing `refresh_task.cancel()` from the lifespan —
        or `register_instruments()` — went undetected.
        """
        import asyncio

        from app.core.config import settings as app_settings
        from app.main import app, lifespan
        from tests.conftest import TestSessionLocal

        monkeypatch.setattr(app_settings, "otel_enabled", True)
        monkeypatch.setattr(app_settings, "fleet_metrics_refresh_seconds", 60)
        monkeypatch.setattr("app.main.AsyncSessionLocal", TestSessionLocal)
        # The lifespan calls shutdown_telemetry() on exit, which would tear down
        # the session-scoped providers and detach the log handler for every
        # later test. Shutdown has its own test; here we only exercise the
        # refresh task's lifecycle.
        monkeypatch.setattr("app.main.shutdown_telemetry", lambda: None)

        # Spy rather than checking for emitted metrics: instrument registration
        # is process-global and idempotent, so another test having registered
        # them already would mask the lifespan skipping it entirely.
        registered = False
        real_register = metrics_module.register_instruments

        def _spy() -> None:
            nonlocal registered
            registered = True
            real_register()

        monkeypatch.setattr("app.main.register_instruments", _spy)

        before = {t for t in asyncio.all_tasks()}
        # Bounded: if the lifespan ever stops cancelling the task, `await
        # refresh_task` on exit never returns and the whole suite hangs. A
        # timeout turns that into a fast, readable failure.
        async with asyncio.timeout(10), lifespan(app):
            await asyncio.sleep(0.15)
            created = {t for t in asyncio.all_tasks()} - before
            assert created, "lifespan started no refresh task"
            refresh_task = created.pop()
            assert not refresh_task.done()

            assert registered, (
                "the lifespan did not register instruments — production would "
                "emit no fleet-health metrics while looking fully configured"
            )

        await asyncio.sleep(0.05)
        assert refresh_task.done(), (
            "the refresh task outlived the lifespan — it was never cancelled"
        )
