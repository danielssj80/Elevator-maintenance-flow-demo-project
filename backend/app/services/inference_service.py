"""Re-score the in-scope fleet from persisted telemetry.

The three decisions worth knowing before changing anything here:

**Kelvin is applied once, and checked.** Readings are stored in Celsius; the
booster was trained on absolute temperatures. The conversion happens in
``build_feature_row`` and nowhere else, and the resulting columns are range-
checked before a single row is scored. The check is on the input rather than on
the output because the output tells you nothing: feeding Celsius to this model
does not collapse the fleet, it leaves 51 of 70 scores distinct and the standard
deviation within 0.002 of correct while moving 10 elevators into the wrong risk
band. Corrupted output that survives every distributional check is why the guard
sits where it does.

**An elevator with no telemetry is skipped, not scored.** Not zeroed, not
trend-shifted, not touched. A unit that stopped reporting must read as stale; a
default-valued score would read as healthy.

**The trend window shifts on date change, not per run.** Runs fire more than
once a day, so a second run overwrites today's point rather than sliding the
window and quietly breaking the documented "index 5 = today" contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.telemetry import get_tracer
from app.ml.feature_mapping import (
    FEATURE_NAME_MAP,
    format_value,
    nl_explanation,
    risk_level,
    tool_wear_from_run_hours,
    type_one_hot,
)
from app.models.elevator import Elevator, ElevatorFeature, ElevatorTrendPoint
from app.repositories.elevator_repository import ElevatorRepository
from app.repositories.telemetry_repository import TelemetryRepository, WindowAggregate
from app.services.inference_client import InferenceClient

KELVIN_OFFSET = 273.15

# A plausible band for an absolute temperature reading from an elevator machine
# room. Generous on both sides — -73 C to 127 C — because the point is not to
# validate the sensor but to catch a unit error: Celsius values land at 20-40,
# nowhere near it.
MIN_PLAUSIBLE_KELVIN = 200.0
MAX_PLAUSIBLE_KELVIN = 400.0

KELVIN_COLUMNS = ("Air_temperature__K", "Process_temperature__K")

tracer = get_tracer(__name__)

# Arbitrary but fixed: the advisory-lock namespace for an inference run.
RUN_LOCK_KEY = 8_531_207

TREND_LENGTH = 6
TOP_FEATURE_COUNT = 3


class FeatureBuildError(RuntimeError):
    """The feature matrix could not be built as the booster requires it."""


@dataclass
class RunSummary:
    scored: int
    skipped_no_telemetry: int
    skipped_out_of_range: int
    out_of_scope: int
    readings_considered: int
    model_version: str | None
    window_hours: int
    duration_seconds: float
    pruned_readings: int


def build_feature_row(
    elevator: Elevator, aggregate: WindowAggregate, feature_names: list[str]
) -> list[float]:
    """One row in the booster's own column order.

    The order comes from the caller, which read it from the model. Hardcoding it
    here would let a retrained model with reordered columns produce entirely
    valid-looking scores from the wrong values.
    """
    values: dict[str, float] = {
        # The only place Celsius becomes Kelvin.
        "Air_temperature__K": aggregate.ambient_temperature_c + KELVIN_OFFSET,
        "Process_temperature__K": aggregate.motor_temperature_c + KELVIN_OFFSET,
        "Rotational_speed__rpm": aggregate.motor_speed_rpm,
        "Torque__Nm": aggregate.load_torque_nm,
        "Tool_wear__min": tool_wear_from_run_hours(
            aggregate.motor_run_hours_cumulative,
            building_type=elevator.building_type,
            hourly_trips_avg=elevator.hourly_trips_avg,
            age_years=elevator.age_years,
        ),
        "Type_L": type_one_hot(elevator.building_type)[0],
        "Type_M": type_one_hot(elevator.building_type)[1],
    }

    missing = [name for name in feature_names if name not in values]
    if missing:
        raise FeatureBuildError(
            f"the model expects features this mapping cannot supply: {missing}"
        )

    return [values[name] for name in feature_names]


def out_of_band_row_indices(
    feature_names: list[str], rows: list[list[float]]
) -> list[int]:
    """Indices of rows whose temperature columns are not plausible Kelvin.

    Separating "which rows" from "what to do about it" is the point. Two very
    different faults produce an out-of-band row, and they need opposite
    responses:

    * **Every** row out of band means the conversion itself is broken — a code
      fault. Scoring anything would produce plausible, wrong numbers for the
      whole fleet, so the run must stop.
    * **Some** rows out of band means bad data from one or two sensors. Stopping
      the fleet for that is the wrong trade: one broken sensor would block every
      other elevator's score, on every run, until someone noticed. Those
      elevators are skipped and reported instead.

    Ingest validation now rejects implausible Celsius at the door, so this is
    the second line rather than the first.
    """
    indices: list[int] = []
    for column in KELVIN_COLUMNS:
        if column not in feature_names:
            continue
        index = feature_names.index(column)
        for row_number, row in enumerate(rows):
            value = row[index]
            if not MIN_PLAUSIBLE_KELVIN <= value <= MAX_PLAUSIBLE_KELVIN:
                indices.append(row_number)
    return sorted(set(indices))


def assert_conversion_is_not_broken(
    feature_names: list[str], rows: list[list[float]], out_of_band: list[int]
) -> None:
    """Stop the run when *every* row is out of band.

    That is the signature of a dropped or doubled conversion, not of a bad
    sensor, and it is the fault this guard was built for.
    """
    if rows and len(out_of_band) == len(rows):
        index = feature_names.index(KELVIN_COLUMNS[0])
        raise FeatureBuildError(
            f"every row is outside the plausible absolute temperature band "
            f"[{MIN_PLAUSIBLE_KELVIN}, {MAX_PLAUSIBLE_KELVIN}] "
            f"(first value: {rows[0][index]:.2f}). This is the shape of a broken "
            "Celsius-to-Kelvin conversion, not of bad sensor data: scoring would "
            "produce plausible but wrong numbers for the entire fleet."
        )


def _top_features(
    feature_names: list[str], row: list[float], contributions: list[float]
) -> list[dict]:
    """Top three features by absolute contribution, impacts normalised to 1.0."""
    ranked = sorted(
        range(len(feature_names)), key=lambda i: abs(contributions[i]), reverse=True
    )[:TOP_FEATURE_COUNT]
    total = sum(abs(contributions[i]) for i in ranked)

    if total == 0:
        # A degenerate contribution vector — every feature contributing exactly
        # nothing. Without this the normalisation below divides by zero and the
        # run dies with an unhandled ZeroDivisionError and a stack trace, and
        # the impact-sum check in _apply never gets the chance to fire.
        raise FeatureBuildError(
            "the model returned an all-zero contribution vector, so feature "
            "impacts cannot be normalised"
        )

    return [
        {
            "name": FEATURE_NAME_MAP.get(feature_names[i], feature_names[i]),
            "impact": round(abs(contributions[i]) / total, 3),
            "value": format_value(feature_names[i], row[i], contributions[i]),
            "direction": "increases" if contributions[i] > 0 else "decreases",
        }
        for i in ranked
    ]


class InferenceService:
    def __init__(
        self,
        session: AsyncSession,
        elevator_repository: ElevatorRepository,
        telemetry_repository: TelemetryRepository,
        inference_client: InferenceClient,
    ) -> None:
        self._session = session
        self._elevator_repo = elevator_repository
        self._telemetry_repo = telemetry_repository
        self._client = inference_client

    async def run(self, now: datetime | None = None) -> RunSummary:
        with tracer.start_as_current_span("inference.run") as span:
            summary = await self._run(now)
            # Counts and shape only — no elevator telemetry on the span. The
            # skipped count is the one worth alerting on: it is how a fleet that
            # quietly stopped reporting becomes visible.
            span.set_attribute("inference.scored", summary.scored)
            span.set_attribute("inference.skipped_no_telemetry", summary.skipped_no_telemetry)
            span.set_attribute("inference.skipped_out_of_range", summary.skipped_out_of_range)
            span.set_attribute("inference.out_of_scope", summary.out_of_scope)
            span.set_attribute("inference.readings_considered", summary.readings_considered)
            span.set_attribute("inference.window_hours", summary.window_hours)
            span.set_attribute("inference.pruned_readings", summary.pruned_readings)
            if summary.model_version is not None:
                span.set_attribute("inference.model_version", summary.model_version)
            return summary

    async def _run(self, now: datetime | None = None) -> RunSummary:
        started = datetime.now(UTC)
        now = now or started
        window_start = now - timedelta(hours=settings.inference_window_hours)

        await self._acquire_run_lock()

        elevators = await self._elevator_repo.list_all()
        in_scope = [e for e in elevators if e.in_model_scope]
        out_of_scope_count = len(elevators) - len(in_scope)

        aggregates = await self._telemetry_repo.aggregate_window(window_start, until=now)

        targets = [e for e in in_scope if e.id in aggregates]
        skipped = [e for e in in_scope if e.id not in aggregates]

        if not targets:
            # Prune anyway. A fleet with nothing to score is precisely when
            # stale rows pile up, and an early return that skips the prune
            # means retention stops working exactly when it is needed.
            return RunSummary(
                scored=0,
                skipped_no_telemetry=len(skipped),
                skipped_out_of_range=0,
                out_of_scope=out_of_scope_count,
                readings_considered=0,
                model_version=None,
                window_hours=settings.inference_window_hours,
                duration_seconds=(datetime.now(UTC) - started).total_seconds(),
                pruned_readings=await self._prune(now),
            )

        feature_names = await self._client.feature_names()
        rows = [build_feature_row(e, aggregates[e.id], feature_names) for e in targets]

        out_of_band = out_of_band_row_indices(feature_names, rows)
        assert_conversion_is_not_broken(feature_names, rows, out_of_band)

        if out_of_band:
            excluded = set(out_of_band)
            skipped_out_of_range = [targets[i].id for i in out_of_band]
            targets = [e for i, e in enumerate(targets) if i not in excluded]
            rows = [r for i, r in enumerate(rows) if i not in excluded]
        else:
            skipped_out_of_range = []

        if targets:
            scores, contributions, model_version = await self._client.score(
                feature_names, rows
            )
            for elevator, row, score, contribution in zip(
                targets, rows, scores, contributions, strict=True
            ):
                await self._apply(elevator, feature_names, row, score, contribution, now)
        else:
            model_version = None

        pruned = await self._prune(now)

        return RunSummary(
            scored=len(targets),
            skipped_no_telemetry=len(skipped),
            skipped_out_of_range=len(skipped_out_of_range),
            out_of_scope=out_of_scope_count,
            readings_considered=sum(aggregates[e.id].reading_count for e in targets),
            model_version=model_version,
            window_hours=settings.inference_window_hours,
            duration_seconds=(datetime.now(UTC) - started).total_seconds(),
            pruned_readings=pruned,
        )

    async def _prune(self, now: datetime) -> int:
        return await self._telemetry_repo.prune(
            cutoff=now - timedelta(days=settings.telemetry_retention_days),
            future_cutoff=now,
        )

    async def _acquire_run_lock(self) -> None:
        """Serialise concurrent runs for the whole transaction.

        Without it two overlapping runs each read `last_scored_at` before the
        other commits, both conclude the elevator has not been scored today, and
        both shift the trend window — so a single day advances it twice and the
        oldest real point is lost. Measured, not theorised: two concurrent
        `POST /api/inference/run` against the live stack both returned 200 and
        both took the new-day branch.

        This is the exact overlap the date-change rule exists to make safe (a
        manual demo trigger landing on top of the schedule), so the rule needs
        the lock to actually hold.

        `pg_advisory_xact_lock` is released when the transaction ends, whether
        it commits or rolls back — no cleanup path to get wrong. The second run
        waits rather than failing: a run is short, and a caller that asked for a
        re-score would rather wait than get a 409.
        """
        await self._session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": RUN_LOCK_KEY})

    async def _apply(
        self,
        elevator: Elevator,
        feature_names: list[str],
        row: list[float],
        score: float,
        contribution: list[float],
        now: datetime,
    ) -> None:
        rounded = round(score, 4)
        level = risk_level(rounded)
        features = _top_features(feature_names, row, contribution)

        impact_total = sum(f["impact"] for f in features)
        if not 0.99 <= impact_total <= 1.01:
            raise FeatureBuildError(
                f"{elevator.id}: feature impacts sum to {impact_total}, expected 1.0"
            )

        # Read before the write: _shift_trend needs to know whether this
        # elevator was already scored today, and assigning last_scored_at first
        # would make every run look like a same-day rerun, so the window would
        # never advance.
        scored_today = (
            elevator.last_scored_at is not None
            and elevator.last_scored_at.date() == now.date()
        )

        elevator.risk_score = rounded
        elevator.risk_level = level
        elevator.nl_explanation = nl_explanation(level, features)
        elevator.last_scored_at = now

        await self._replace_features(elevator, features)
        await self._shift_trend(elevator, rounded, scored_today=scored_today)

    async def _replace_features(self, elevator: Elevator, features: list[dict]) -> None:
        await self._session.execute(
            delete(ElevatorFeature).where(ElevatorFeature.elevator_id == elevator.id)
        )
        self._session.add_all(
            [
                ElevatorFeature(
                    elevator_id=elevator.id,
                    name=f["name"],
                    impact=f["impact"],
                    value=f["value"],
                    direction=f["direction"],
                )
                for f in features
            ]
        )

    async def _shift_trend(
        self, elevator: Elevator, score: float, *, scored_today: bool
    ) -> None:
        """Rewrite the six trend points.

        DELETE all six and INSERT six, never `UPDATE ... SET day_index =
        day_index - 1`. The unique constraint on (elevator_id, day_index) is
        non-deferrable and checked per row, so the in-place decrement can raise
        a duplicate-key violation depending on the order the rows happen to be
        updated in — even though the final state is unique. It passes in testing
        and fails later, non-deterministically. Six rows per elevator makes the
        rewrite free.
        """
        result = await self._session.execute(
            select(ElevatorTrendPoint)
            .where(ElevatorTrendPoint.elevator_id == elevator.id)
            .order_by(ElevatorTrendPoint.day_index)
        )
        existing = [tp.score for tp in result.scalars().all()]

        # Pad or trim to the contract length: a fleet seeded from a run that
        # produced fewer points must still end up with exactly six.
        if len(existing) < TREND_LENGTH:
            existing = [score] * (TREND_LENGTH - len(existing)) + existing
        elif len(existing) > TREND_LENGTH:
            existing = existing[-TREND_LENGTH:]

        if scored_today:
            # Second or later run of the same day: today's point is replaced,
            # the window does not move.
            updated = existing[:-1] + [score]
        else:
            updated = existing[1:] + [score]

        await self._session.execute(
            delete(ElevatorTrendPoint).where(ElevatorTrendPoint.elevator_id == elevator.id)
        )
        self._session.add_all(
            [
                ElevatorTrendPoint(elevator_id=elevator.id, day_index=i, score=s)
                for i, s in enumerate(updated)
            ]
        )
