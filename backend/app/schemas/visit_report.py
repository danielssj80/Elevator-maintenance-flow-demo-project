from pydantic import BaseModel, ConfigDict


class PostVisitReportSchema(BaseModel):
    technician_name: str
    visit_date: str
    failure_found: bool
    components_replaced: list[str] = []
    parameters_corrected: list[str] = []
    notes: str = ""


class ReportResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str
    message: str
