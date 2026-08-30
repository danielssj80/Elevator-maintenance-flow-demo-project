from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.elevator import Elevator, ElevatorFeature, ElevatorTrendPoint
from app.models.telemetry import TelemetryReading
from app.repositories.elevator_repository import ElevatorRepository
from app.repositories.telemetry_repository import TelemetryRepository, WindowAggregate
from app.services.inference_service import (
    FeatureBuildError,
    InferenceService,
    assert_temperatures_are_absolute,
    build_feature_row,
)

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)

FEATURE_NAMES = [
    "Air_temperature__K",
    "Process_temperature__K",
    "Rotational_speed__rpm",
    "Torque__Nm",
    "Tool_wear__min",
    "Type_L",
    "Type_M",
]


def _elevator(
    id: str,
    *,
    in_scope: bool = True,
    building_type: str = "office",
    last_scored_at: datetime | None = None,
    trend: list[float] | None = None,
) -> Elevator:
    return Elevator(
        id=id,
        building_name="Test Building",
        building_type=building_type,
        floor_count=5,
        model="Test Model",
        brand="own",
        age_years=3,
        risk_score=0.4,
        risk_level="low",
        last_visit_date="2026-01-01",
        last_visit_technician="Ana",
        last_visit_notes="ok",
        nl_explanation="seeded",
        in_model_scope=in_scope,
        hourly_trips_avg=10,
        zone="Madrid",
        last_scored_at=last_scored_at,
        features=[
            ElevatorFeature(name="Seeded", impact=1.0, value="x", direction="increases")
        ],
        trend_points=[
            ElevatorTrendPoint(day_index=i, score=s)
            for i, s in enumerate(trend if trend is not None else [0.1] * 6)
        ],
    )


def _aggregate(
    elevator_id: str,
    *,
    ambient_c: float = 27.0,
    motor_c: float = 37.0,
    rpm: float = 1500.0,
    torque: float = 40.0,
    run_hours: float | None = 12_000.0,
    count: int = 4,
) -> WindowAggregate:
    return WindowAggregate(
        elevator_id=elevator_id,
        ambient_temperature_c=ambient_c,
        motor_temperature_c=motor_c,
        motor_speed_rpm=rpm,
        load_torque_nm=torque,
        motor_run_hours_cumulative=run_hours,
        reading_count=count,
    )


def _reading(elevator_id: str, minutes_ago: int = 5, **kw) -> TelemetryReading:
    return TelemetryReading(
        elevator_id=elevator_id,
        recorded_at=NOW - timedelta(minutes=minutes_ago),
        ingested_at=NOW,
        ambient_temperature_c=kw.get("ambient_c", 27.0),
        motor_temperature_c=kw.get("motor_c", 37.0),
        motor_speed_rpm=kw.get("rpm", 1500.0),
        load_torque_nm=kw.get("torque", 40.0),
        motor_run_hours_cumulative=kw.get("run_hours", 12_000.0),
        source="test",
        batch_id="b1",
        trace_id=None,
    )


class FakeInferenceClient:
    """Records what it was asked to score, so the matrix itself can be asserted."""

    def __init__(self, scores: list[float] | None = None) -> None:
        self._scores = scores
        self.received_feature_names: list[str] | None = None
        self.received_rows: list[list[float]] | None = None

    async def feature_names(self) -> list[str]:
        return list(FEATURE_NAMES)

    async def score(self, feature_names, rows):
        self.received_feature_names = feature_names
        self.received_rows = rows
        if self._scores is None:
            scores = [0.9] * len(rows)
        elif len(self._scores) == 1:
            scores = self._scores * len(rows)
        else:
            scores = self._scores
        # One contribution per feature, distinct magnitudes so the top-3 is
        # unambiguous.
        contributions = [[0.5, -0.4, 0.3, -0.2, 0.1, 0.05, -0.01] for _ in rows]
        return scores[: len(rows)], contributions, "model-abc"


def _service(db_session, client: FakeInferenceClient) -> InferenceService:
    return InferenceService(
        session=db_session,
        elevator_repository=ElevatorRepository(db_session),
        telemetry_repository=TelemetryRepository(db_session),
        inference_client=client,
    )


# ── The Kelvin boundary ──────────────────────────────────────────────────────


def test_celsius_becomes_kelvin_in_the_feature_matrix():
    """27.0 C must reach the model as 300.15 K. The single most important
    assertion in this change: nothing downstream raises if it does not."""
    row = build_feature_row(_elevator("ELV-K1"), _aggregate("ELV-K1", ambient_c=27.0), FEATURE_NAMES)

    assert row[FEATURE_NAMES.index("Air_temperature__K")] == pytest.approx(300.15)


def test_both_temperature_columns_are_converted():
    row = build_feature_row(
        _elevator("ELV-K2"),
        _aggregate("ELV-K2", ambient_c=20.0, motor_c=30.0),
        FEATURE_NAMES,
    )

    assert row[FEATURE_NAMES.index("Air_temperature__K")] == pytest.approx(293.15)
    assert row[FEATURE_NAMES.index("Process_temperature__K")] == pytest.approx(303.15)


def test_non_temperature_columns_are_not_offset():
    """The offset must apply to temperatures only, not to every numeric column."""
    row = build_feature_row(
        _elevator("ELV-K3"), _aggregate("ELV-K3", rpm=1500.0, torque=40.0), FEATURE_NAMES
    )

    assert row[FEATURE_NAMES.index("Rotational_speed__rpm")] == pytest.approx(1500.0)
    assert row[FEATURE_NAMES.index("Torque__Nm")] == pytest.approx(40.0)


@pytest.mark.asyncio
async def test_the_conversion_is_applied_exactly_once(db_session):
    """A second application would land at 573.3, which the band check catches,
    so this asserts the value the model actually receives."""
    db_session.add(_elevator("ELV-K4"))
    await db_session.flush()
    db_session.add(_reading("ELV-K4", ambient_c=27.0))
    await db_session.flush()

    client = FakeInferenceClient()
    await _service(db_session, client).run(now=NOW)

    index = client.received_feature_names.index("Air_temperature__K")
    assert client.received_rows[0][index] == pytest.approx(300.15)


def test_a_celsius_row_is_rejected_before_scoring():
    """The guard that replaces the plan's fleet-variance canary."""
    celsius_row = [27.0, 37.0, 1500.0, 40.0, 100.0, 0.0, 1.0]

    with pytest.raises(FeatureBuildError) as exc:
        assert_temperatures_are_absolute(FEATURE_NAMES, [celsius_row])

    assert "Air_temperature__K" in str(exc.value)


@pytest.mark.asyncio
async def test_the_run_refuses_to_score_an_out_of_band_temperature(db_session):
    """The band check must be wired into run(), not merely exist.

    Added after a mutation run: deleting the assert_temperatures_are_absolute
    call from run() left all 22 tests green, because the only test covering it
    called the function directly. A guard nothing exercises through the real
    path is decoration.
    """
    db_session.add(_elevator("ELV-B1"))
    await db_session.flush()
    # Physically impossible, and 273.15 short of plausible even after
    # conversion — the shape a dropped or wrong conversion produces.
    db_session.add(_reading("ELV-B1", ambient_c=-400.0))
    await db_session.flush()

    with pytest.raises(FeatureBuildError) as exc:
        await _service(db_session, FakeInferenceClient()).run(now=NOW)

    assert "Air_temperature__K" in str(exc.value)

    await db_session.flush()
    db_session.expire_all()
    elevator = await ElevatorRepository(db_session).get_by_id("ELV-B1")
    assert elevator.risk_score == 0.4, "nothing may be scored once the guard fires"
    assert elevator.last_scored_at is None


@pytest.mark.asyncio
async def test_the_run_never_reaches_the_model_with_an_out_of_band_row(db_session):
    """And it must fail before the client is called, not after."""
    db_session.add(_elevator("ELV-B2"))
    await db_session.flush()
    db_session.add(_reading("ELV-B2", ambient_c=-400.0))
    await db_session.flush()

    client = FakeInferenceClient()
    with pytest.raises(FeatureBuildError):
        await _service(db_session, client).run(now=NOW)

    assert client.received_rows is None, "the scorer must not be called at all"


def test_plausible_kelvin_rows_pass_the_band_check():
    for celsius in (-40.0, 0.0, 27.0, 80.0):
        row = build_feature_row(
            _elevator("ELV-K5"), _aggregate("ELV-K5", ambient_c=celsius, motor_c=celsius), FEATURE_NAMES
        )
        assert_temperatures_are_absolute(FEATURE_NAMES, [row])


# ── Column order ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_matrix_follows_the_booster_column_order(db_session):
    db_session.add(_elevator("ELV-C1"))
    await db_session.flush()
    db_session.add(_reading("ELV-C1"))
    await db_session.flush()

    client = FakeInferenceClient()
    await _service(db_session, client).run(now=NOW)

    assert client.received_feature_names == FEATURE_NAMES

    # Names alone are not the guarantee: a row whose values are ordered
    # differently from the names it is sent with scores plausibly from the
    # wrong features. Assert each value sits under its own column.
    row = client.received_rows[0]
    expected = {
        "Air_temperature__K": 300.15,
        "Process_temperature__K": 310.15,
        "Rotational_speed__rpm": 1500.0,
        "Torque__Nm": 40.0,
        "Type_L": 0.0,
        "Type_M": 1.0,
    }
    for column, value in expected.items():
        assert row[client.received_feature_names.index(column)] == pytest.approx(value), column


def test_a_feature_the_mapping_cannot_supply_is_an_error():
    with pytest.raises(FeatureBuildError) as exc:
        build_feature_row(
            _elevator("ELV-C2"), _aggregate("ELV-C2"), [*FEATURE_NAMES, "Vibration_mm_s"]
        )

    assert "Vibration_mm_s" in str(exc.value)


def test_reordering_the_columns_reorders_the_row():
    reversed_names = list(reversed(FEATURE_NAMES))
    row = build_feature_row(_elevator("ELV-C3"), _aggregate("ELV-C3"), reversed_names)

    assert row[reversed_names.index("Air_temperature__K")] == pytest.approx(300.15)


# ── Scope and skipping ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_out_of_scope_elevators_are_never_touched(db_session):
    db_session.add(_elevator("ELV-O1", in_scope=False))
    await db_session.flush()
    db_session.add(_reading("ELV-O1"))
    await db_session.flush()

    client = FakeInferenceClient()
    summary = await _service(db_session, client).run(now=NOW)

    await db_session.flush()
    db_session.expire_all()
    elevator = await ElevatorRepository(db_session).get_by_id("ELV-O1")
    assert elevator.risk_score == 0.4
    assert elevator.nl_explanation == "seeded"
    assert elevator.last_scored_at is None
    assert summary.out_of_scope == 1
    assert summary.scored == 0


@pytest.mark.asyncio
async def test_in_scope_elevator_without_telemetry_is_skipped_not_zeroed(db_session):
    """A unit that stopped reporting must read as stale, not as low risk."""
    db_session.add(_elevator("ELV-N1"))
    await db_session.flush()

    client = FakeInferenceClient()
    summary = await _service(db_session, client).run(now=NOW)

    await db_session.flush()
    db_session.expire_all()
    elevator = await ElevatorRepository(db_session).get_by_id("ELV-N1")
    assert elevator.risk_score == 0.4
    assert elevator.last_scored_at is None
    assert [tp.score for tp in elevator.trend_points] == [0.1] * 6
    assert summary.skipped_no_telemetry == 1
    assert summary.scored == 0


@pytest.mark.asyncio
async def test_readings_outside_the_window_do_not_make_an_elevator_eligible(db_session):
    db_session.add(_elevator("ELV-N2"))
    await db_session.flush()
    db_session.add(_reading("ELV-N2", minutes_ago=60 * 48))
    await db_session.flush()

    client = FakeInferenceClient()
    summary = await _service(db_session, client).run(now=NOW)

    assert summary.scored == 0
    assert summary.skipped_no_telemetry == 1


# ── Motor life fallback ──────────────────────────────────────────────────────


def test_missing_run_hours_falls_back_to_the_offline_proxy():
    """Must match the offline generator's proxy, not a convenient default."""
    from app.ml.feature_mapping import MAX_MOTOR_HOURS, RUN_PARAMS

    elevator = _elevator("ELV-M1", building_type="infrastructure")
    row = build_feature_row(elevator, _aggregate("ELV-M1", run_hours=None), FEATURE_NAMES)

    run_min_per_trip, active_hours = RUN_PARAMS["infrastructure"]
    expected_hours = (
        elevator.hourly_trips_avg * active_hours * run_min_per_trip / 60.0 * 365 * elevator.age_years
    )
    expected = min(1.0, expected_hours / MAX_MOTOR_HOURS) * 253.0

    assert row[FEATURE_NAMES.index("Tool_wear__min")] == pytest.approx(expected)


def test_reported_run_hours_are_used_when_present():
    row = build_feature_row(_elevator("ELV-M2"), _aggregate("ELV-M2", run_hours=20_000.0), FEATURE_NAMES)

    assert row[FEATURE_NAMES.index("Tool_wear__min")] == pytest.approx(0.5 * 253.0)


def test_run_hours_beyond_the_rated_life_are_clamped():
    row = build_feature_row(_elevator("ELV-M3"), _aggregate("ELV-M3", run_hours=10_000_000.0), FEATURE_NAMES)

    assert row[FEATURE_NAMES.index("Tool_wear__min")] == pytest.approx(253.0)


# ── Trend window ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_first_run_of_a_new_day_shifts_the_window(db_session):
    db_session.add(
        _elevator(
            "ELV-T1",
            last_scored_at=NOW - timedelta(days=1),
            trend=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
        )
    )
    await db_session.flush()
    db_session.add(_reading("ELV-T1"))
    await db_session.flush()

    await _service(db_session, FakeInferenceClient([0.9])).run(now=NOW)

    await db_session.flush()
    db_session.expire_all()
    elevator = await ElevatorRepository(db_session).get_by_id("ELV-T1")
    trend = [tp.score for tp in sorted(elevator.trend_points, key=lambda t: t.day_index)]
    assert trend == [0.2, 0.3, 0.4, 0.5, 0.6, 0.9]


@pytest.mark.asyncio
async def test_second_run_of_the_same_day_overwrites_index_five(db_session):
    db_session.add(
        _elevator(
            "ELV-T2",
            last_scored_at=NOW - timedelta(hours=2),
            trend=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
        )
    )
    await db_session.flush()
    db_session.add(_reading("ELV-T2"))
    await db_session.flush()

    await _service(db_session, FakeInferenceClient([0.9])).run(now=NOW)

    await db_session.flush()
    db_session.expire_all()
    elevator = await ElevatorRepository(db_session).get_by_id("ELV-T2")
    trend = [tp.score for tp in sorted(elevator.trend_points, key=lambda t: t.day_index)]
    assert trend == [0.1, 0.2, 0.3, 0.4, 0.5, 0.9]


@pytest.mark.asyncio
async def test_ten_consecutive_shifts_never_violate_the_unique_constraint(db_session):
    """The trap this DELETE+INSERT exists to avoid.

    `UPDATE ... SET day_index = day_index - 1` can raise a duplicate-key
    violation depending on row order even when the final state is unique, and
    it does so non-deterministically.
    """
    db_session.add(_elevator("ELV-T3", trend=[0.1] * 6))
    await db_session.flush()
    db_session.add(_reading("ELV-T3"))
    await db_session.flush()

    for day in range(10):
        score = round(0.10 + day * 0.05, 4)
        run_at = NOW + timedelta(days=day)
        db_session.add(_reading("ELV-T3", minutes_ago=-day * 24 * 60 + 5))
        await db_session.flush()
        await _service(db_session, FakeInferenceClient([score])).run(now=run_at)
        await db_session.flush()

        result = await db_session.execute(
            select(ElevatorTrendPoint)
            .where(ElevatorTrendPoint.elevator_id == "ELV-T3")
            .order_by(ElevatorTrendPoint.day_index)
        )
        points = list(result.scalars().all())
        assert len(points) == 6, f"day {day}: trend length {len(points)}"
        assert [p.day_index for p in points] == [0, 1, 2, 3, 4, 5]
        assert points[5].score == pytest.approx(score), f"day {day}: index 5 must be today"


# ── Features and explanation ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_three_features_are_persisted_with_impacts_summing_to_one(db_session):
    db_session.add(_elevator("ELV-F1"))
    await db_session.flush()
    db_session.add(_reading("ELV-F1"))
    await db_session.flush()

    await _service(db_session, FakeInferenceClient()).run(now=NOW)

    await db_session.flush()
    db_session.expire_all()
    elevator = await ElevatorRepository(db_session).get_by_id("ELV-F1")
    assert len(elevator.features) == 3
    assert 0.99 <= sum(f.impact for f in elevator.features) <= 1.01
    assert all(f.direction in ("increases", "decreases") for f in elevator.features)
    # The seeded feature must be gone, not accumulated alongside the new ones.
    assert "Seeded" not in [f.name for f in elevator.features]


@pytest.mark.asyncio
async def test_the_explanation_is_regenerated_from_the_new_features(db_session):
    db_session.add(_elevator("ELV-F2"))
    await db_session.flush()
    db_session.add(_reading("ELV-F2"))
    await db_session.flush()

    await _service(db_session, FakeInferenceClient([0.95])).run(now=NOW)

    await db_session.flush()
    db_session.expire_all()
    elevator = await ElevatorRepository(db_session).get_by_id("ELV-F2")
    assert elevator.nl_explanation != "seeded"
    assert elevator.nl_explanation.startswith("High risk:")


@pytest.mark.asyncio
async def test_the_risk_level_uses_the_shared_threshold_rule(db_session):
    for score, expected in ((0.85, "high"), (0.60, "medium"), (0.20, "low")):
        elevator_id = f"ELV-L{int(score * 100)}"
        db_session.add(_elevator(elevator_id))
        await db_session.flush()
        db_session.add(_reading(elevator_id))
        await db_session.flush()

        await _service(db_session, FakeInferenceClient([score])).run(now=NOW)

        await db_session.flush()
        db_session.expire_all()
        elevator = await ElevatorRepository(db_session).get_by_id(elevator_id)
        assert elevator.risk_level == expected, f"{score} should be {expected}"


# ── Retention ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_successful_run_prunes_readings_beyond_the_retention_window(db_session):
    db_session.add(_elevator("ELV-P1"))
    await db_session.flush()
    db_session.add(_reading("ELV-P1"))
    db_session.add(_reading("ELV-P1", minutes_ago=60 * 24 * 40))
    await db_session.flush()

    summary = await _service(db_session, FakeInferenceClient()).run(now=NOW)

    assert summary.pruned_readings == 1
    remaining = await TelemetryRepository(db_session).list_for_elevator(
        "ELV-P1", since=NOW - timedelta(days=365), limit=50
    )
    assert len(remaining) == 1


# ── Tracing ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_run_emits_a_domain_span_with_counts(db_session, span_exporter):
    db_session.add(_elevator("ELV-S1"))
    db_session.add(_elevator("ELV-S2"))          # in scope, no telemetry
    db_session.add(_elevator("ELV-S3", in_scope=False))
    await db_session.flush()
    db_session.add(_reading("ELV-S1"))
    await db_session.flush()

    await _service(db_session, FakeInferenceClient()).run(now=NOW)

    spans = [s for s in span_exporter.get_finished_spans() if s.name == "inference.run"]
    assert len(spans) == 1

    attributes = dict(spans[0].attributes)
    assert attributes["inference.scored"] == 1
    assert attributes["inference.skipped_no_telemetry"] == 1
    assert attributes["inference.out_of_scope"] == 1
    assert attributes["inference.model_version"] == "model-abc"


@pytest.mark.asyncio
async def test_the_run_span_carries_no_telemetry_values(db_session, span_exporter):
    """Counts and shape only.

    Fleet operating data on a span is the same mistake as prompt content on a
    briefing span: it leaves the database, crosses the Collector, and lands in a
    backend with different retention and different access control.
    """
    db_session.add(_elevator("ELV-S4"))
    await db_session.flush()
    db_session.add(_reading("ELV-S4", ambient_c=31.5, torque=47.25))
    await db_session.flush()

    await _service(db_session, FakeInferenceClient()).run(now=NOW)

    spans = [s for s in span_exporter.get_finished_spans() if s.name == "inference.run"]
    rendered = " ".join(f"{k}={v}" for k, v in spans[0].attributes.items())

    for leaked in ("31.5", "47.25", "304.65"):
        assert leaked not in rendered, f"{leaked} must not appear on the span"
