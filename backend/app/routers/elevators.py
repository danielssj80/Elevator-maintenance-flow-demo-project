from fastapi import APIRouter, HTTPException
from app.models import ElevatorSummary, ElevatorDetail, PostVisitReport, ReportResponse
from app.data import ELEVATORS, ELEVATOR_INDEX

router = APIRouter(prefix="/api/elevators", tags=["elevators"])


@router.get("", response_model=list[ElevatorSummary])
def list_elevators():
    return ELEVATORS


@router.get("/{elevator_id}", response_model=ElevatorDetail)
def get_elevator(elevator_id: str):
    elevator = ELEVATOR_INDEX.get(elevator_id)
    if not elevator:
        raise HTTPException(status_code=404, detail="Elevator not found")
    return elevator


@router.post("/{elevator_id}/report", response_model=ReportResponse)
def submit_report(elevator_id: str, report: PostVisitReport):
    if elevator_id not in ELEVATOR_INDEX:
        raise HTTPException(status_code=404, detail="Elevator not found")
    # In production this would persist to DB and trigger retraining label
    return ReportResponse(
        status="ok",
        message=f"Report for {elevator_id} received. Data queued for model retraining.",
    )
