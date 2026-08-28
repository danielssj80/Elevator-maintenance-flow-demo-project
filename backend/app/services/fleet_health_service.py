"""Derives the fleet-health snapshot that backs the observability dashboards."""

from datetime import UTC, datetime

from app.core.metrics import RISK_LEVELS, FleetHealthSnapshot
from app.repositories.elevator_repository import ElevatorRepository
from app.services.elevator_service import _derive_risk_level


class FleetHealthService:
    """Aggregates fleet state for metric reporting.

    Risk level is derived here rather than read from the database, reusing the
    same rule the API uses, so the dashboard and the technician's list can
    never disagree about what "high risk" means.
    """

    def __init__(self, elevator_repository: ElevatorRepository) -> None:
        self._elev_repo = elevator_repository

    async def compute_snapshot(self) -> FleetHealthSnapshot:
        elevators = await self._elev_repo.list_all()

        counts = dict.fromkeys(RISK_LEVELS, 0)
        for elevator in elevators:
            # Out-of-scope units are never run through the model: their score is
            # a placeholder, not a low risk. Bucketing them as "low" would
            # misreport a unit nobody is monitoring as a healthy one.
            if not elevator.in_model_scope:
                counts["out_of_scope"] += 1
                continue
            counts[_derive_risk_level(elevator.risk_score)] += 1

        return FleetHealthSnapshot(
            counts_by_risk_level=counts,
            # Both arrive with the telemetry-ingestion change. Reported as
            # unknown rather than zero until then.
            last_inference_run_at=None,
            stale_telemetry_count=None,
            captured_at=datetime.now(UTC),
        )
