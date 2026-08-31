from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.models.elevator import Elevator
from app.repositories.telemetry_repository import TelemetryRepository
from app.schemas.telemetry import TelemetryBatchSchema, TelemetryReadingInput
from app.services.telemetry_service import TelemetryService

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


def _make_elevator(id: str) -> Elevator:
    return Elevator(
        id=id,
        building_name="Test Building",
        building_type="office",
        floor_count=5,
        model="Test Model",
        brand="own",
        age_years=3,
        risk_score=0.4,
        risk_level="low",
        last_visit_date="2026-01-01",
        last_visit_technician="Ana",
        last_visit_notes="ok",
        nl_explanation="all good",
        in_model_scope=True,
        hourly_trips_avg=10,
        zone="Madrid",
    )


def _reading(elevator_id: str, minutes_ago: int = 0) -> TelemetryReadingInput:
    return TelemetryReadingInput(
        elevator_id=elevator_id,
        recorded_at=NOW - timedelta(minutes=minutes_ago),
        ambient_temperature_c=27.0,
        motor_temperature_c=37.0,
        motor_speed_rpm=1500.0,
        load_torque_nm=40.0,
        motor_run_hours_cumulative=12_000.0,
    )


def _service(db_session) -> TelemetryService:
    from app.repositories.elevator_repository import ElevatorRepository

    return TelemetryService(
        telemetry_repository=TelemetryRepository(db_session),
        elevator_repository=ElevatorRepository(db_session),
    )


@pytest.mark.asyncio
async def test_full_batch_is_accepted_and_shares_one_batch_id(db_session):
    db_session.add(_make_elevator("ELV-S01"))
    await db_session.flush()

    service = _service(db_session)
    result = await service.ingest(
        TelemetryBatchSchema(
            source="test",
            readings=[_reading("ELV-S01", i) for i in range(5)],
        )
    )
    await db_session.flush()

    assert result.accepted == 5
    assert result.rejected_elevator_ids == []

    rows = await TelemetryRepository(db_session).list_for_elevator(
        "ELV-S01", since=NOW - timedelta(hours=1), limit=50
    )
    assert len(rows) == 5
    assert {r.batch_id for r in rows} == {result.batch_id}


@pytest.mark.asyncio
async def test_partial_batch_persists_valid_rows_and_reports_the_rest(db_session):
    """One stale elevator id must not cost a scheduled producer its whole batch."""
    db_session.add(_make_elevator("ELV-S02"))
    await db_session.flush()

    service = _service(db_session)
    result = await service.ingest(
        TelemetryBatchSchema(
            source="test",
            readings=[
                _reading("ELV-S02", 1),
                _reading("ELV-S02", 2),
                _reading("ELV-GONE", 3),
                _reading("ELV-ALSO-GONE", 4),
            ],
        )
    )
    await db_session.flush()

    assert result.accepted == 2
    assert sorted(result.rejected_elevator_ids) == ["ELV-ALSO-GONE", "ELV-GONE"]


@pytest.mark.asyncio
async def test_batch_with_no_valid_readings_is_rejected(db_session):
    service = _service(db_session)

    with pytest.raises(HTTPException) as exc:
        await service.ingest(
            TelemetryBatchSchema(
                source="test",
                readings=[_reading("ELV-NOPE", 1), _reading("ELV-NOPE-2", 2)],
            )
        )

    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_nothing_is_persisted_when_every_reading_is_invalid(db_session):
    service = _service(db_session)

    with pytest.raises(HTTPException):
        await service.ingest(
            TelemetryBatchSchema(source="test", readings=[_reading("ELV-NOPE", 1)])
        )
    await db_session.flush()

    rows = await TelemetryRepository(db_session).list_for_elevator(
        "ELV-NOPE", since=NOW - timedelta(hours=1), limit=50
    )
    assert rows == []


@pytest.mark.asyncio
async def test_readings_are_persisted_in_celsius_untouched(db_session):
    """The service must not pre-convert to the model's Kelvin feature space."""
    db_session.add(_make_elevator("ELV-S03"))
    await db_session.flush()

    service = _service(db_session)
    await service.ingest(
        TelemetryBatchSchema(source="test", readings=[_reading("ELV-S03", 1)])
    )
    await db_session.flush()

    rows = await TelemetryRepository(db_session).list_for_elevator(
        "ELV-S03", since=NOW - timedelta(hours=1), limit=10
    )
    assert rows[0].ambient_temperature_c == 27.0
    assert rows[0].motor_temperature_c == 37.0


@pytest.mark.asyncio
async def test_trace_id_is_recorded_as_32_hex_characters(db_session):
    from opentelemetry import trace

    db_session.add(_make_elevator("ELV-S04"))
    await db_session.flush()

    service = _service(db_session)
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("ingest-test"):
        await service.ingest(
            TelemetryBatchSchema(source="test", readings=[_reading("ELV-S04", 1)])
        )
    await db_session.flush()

    rows = await TelemetryRepository(db_session).list_for_elevator(
        "ELV-S04", since=NOW - timedelta(hours=1), limit=10
    )
    assert rows[0].trace_id is not None
    assert len(rows[0].trace_id) == 32
    assert all(c in "0123456789abcdef" for c in rows[0].trace_id)


@pytest.mark.asyncio
async def test_ingest_succeeds_with_no_recording_span(db_session):
    """Ingest must work with tracing disabled, writing a null trace_id."""
    from opentelemetry import trace

    db_session.add(_make_elevator("ELV-S05"))
    await db_session.flush()

    service = _service(db_session)
    # An explicitly invalid context is what a non-recording span looks like.
    with trace.use_span(trace.NonRecordingSpan(trace.INVALID_SPAN_CONTEXT)):
        result = await service.ingest(
            TelemetryBatchSchema(source="test", readings=[_reading("ELV-S05", 1)])
        )
    await db_session.flush()

    assert result.accepted == 1
    assert result.trace_id is None
    rows = await TelemetryRepository(db_session).list_for_elevator(
        "ELV-S05", since=NOW - timedelta(hours=1), limit=10
    )
    assert rows[0].trace_id is None


def test_batch_larger_than_the_maximum_is_rejected_by_validation():
    """The bound is a schema constraint, so an oversize batch never reaches the service."""
    import pydantic

    from app.schemas.telemetry import MAX_BATCH_SIZE

    with pytest.raises(pydantic.ValidationError):
        TelemetryBatchSchema(
            source="test",
            readings=[_reading("ELV-S06", 1) for _ in range(MAX_BATCH_SIZE + 1)],
        )


def test_empty_batch_is_rejected_by_validation():
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        TelemetryBatchSchema(source="test", readings=[])


# ── Idempotency: what a retrying producer gets back ──────────────────────────


@pytest.mark.asyncio
async def test_a_reading_repeated_within_one_batch_is_persisted_once(db_session):
    """The intra-batch half of the guarantee.

    Nothing in Python enforces this: the single multi-row `INSERT ... ON
    CONFLICT DO NOTHING` skips a row conflicting with one inserted earlier in
    the same statement. A Python pre-deduplication pass was written and removed
    when deleting it left this test green — see `create_many`. So this is the
    only thing holding the rule, and it belongs in the suite rather than in a
    comment.
    """
    db_session.add(_make_elevator("ELV-S20"))
    await db_session.flush()

    result = await _service(db_session).ingest(
        TelemetryBatchSchema(
            source="test",
            readings=[_reading("ELV-S20", 5), _reading("ELV-S20", 5)],
        )
    )
    await db_session.flush()

    assert result.accepted == 1
    assert result.duplicates_ignored == 1


@pytest.mark.asyncio
async def test_a_resubmitted_batch_accepts_nothing_and_counts_every_duplicate(db_session):
    db_session.add(_make_elevator("ELV-S21"))
    await db_session.flush()
    service = _service(db_session)

    def batch() -> TelemetryBatchSchema:
        return TelemetryBatchSchema(
            source="test", readings=[_reading("ELV-S21", i) for i in range(5)]
        )

    first = await service.ingest(batch())
    await db_session.flush()
    retry = await service.ingest(batch())
    await db_session.flush()

    assert (first.accepted, first.duplicates_ignored) == (5, 0)
    assert (retry.accepted, retry.duplicates_ignored) == (0, 5)


@pytest.mark.asyncio
async def test_a_partially_overlapping_batch_splits_accepted_from_duplicates(db_session):
    """The realistic retry: a catch-up batch re-sending the last tick.

    The 1000-reading bound exists precisely to allow this, so it is the case a
    batch-level idempotency key would not have covered.
    """
    db_session.add(_make_elevator("ELV-S22"))
    await db_session.flush()
    service = _service(db_session)

    await service.ingest(
        TelemetryBatchSchema(source="test", readings=[_reading("ELV-S22", i) for i in range(3)])
    )
    await db_session.flush()
    result = await service.ingest(
        TelemetryBatchSchema(source="test", readings=[_reading("ELV-S22", i) for i in range(5)])
    )
    await db_session.flush()

    assert result.accepted == 2
    assert result.duplicates_ignored == 3


@pytest.mark.asyncio
async def test_an_all_duplicate_batch_is_accepted_not_rejected_as_invalid(db_session):
    """A retry is a successful no-op, not a bad request.

    The 422 path exists for a batch referencing no known elevator — a
    misconfigured producer. A batch that is entirely duplicates is a correctly
    configured producer retrying, and must not be told it sent nonsense.
    """
    db_session.add(_make_elevator("ELV-S23"))
    await db_session.flush()
    service = _service(db_session)

    batch = TelemetryBatchSchema(source="test", readings=[_reading("ELV-S23", 5)])
    await service.ingest(batch)
    await db_session.flush()

    result = await service.ingest(
        TelemetryBatchSchema(source="test", readings=[_reading("ELV-S23", 5)])
    )
    assert result.accepted == 0
    assert result.rejected_elevator_ids == []


@pytest.mark.asyncio
async def test_a_retried_batch_does_not_relabel_the_rows_it_already_stored(db_session):
    """Provenance belongs to the request that actually stored the row.

    `batch_id` is minted per request, so a retry carries a new one. It must
    label the rows this request inserted — none — rather than overwrite the
    provenance of rows the first request created.
    """
    db_session.add(_make_elevator("ELV-S24"))
    await db_session.flush()
    service = _service(db_session)

    first = await service.ingest(
        TelemetryBatchSchema(source="test", readings=[_reading("ELV-S24", 5)])
    )
    await db_session.flush()
    retry = await service.ingest(
        TelemetryBatchSchema(source="test", readings=[_reading("ELV-S24", 5)])
    )
    await db_session.flush()

    rows = await TelemetryRepository(db_session).list_for_elevator(
        "ELV-S24", since=NOW - timedelta(hours=1), limit=10
    )
    assert retry.batch_id != first.batch_id
    assert [r.batch_id for r in rows] == [first.batch_id]
