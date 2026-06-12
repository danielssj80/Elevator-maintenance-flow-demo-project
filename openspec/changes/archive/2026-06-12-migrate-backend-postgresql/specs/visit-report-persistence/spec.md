# visit-report-persistence

## ADDED Requirements

### Requirement: Post-visit reports are persisted
The system SHALL store every valid post-visit report as a row in the `visit_reports` table, linked to its elevator, and SHALL respond with `201 Created` and the existing `ReportResponse` shape (`status`, `message`).

#### Scenario: Submitting a valid report
- **WHEN** `POST /api/elevators/{id}/report` is called for an existing elevator with a valid body
- **THEN** a row exists in `visit_reports` with the submitted fields and a `created_at` timestamp, and the response is `201` with the `ReportResponse` shape

#### Scenario: Frontend submission flow is unaffected
- **WHEN** the report form is submitted from the frontend
- **THEN** the success flow behaves exactly as before the migration (the form does not inspect the status code)

### Requirement: Invalid submissions persist nothing
The system SHALL reject reports for unknown elevators or with invalid bodies without writing to the database.

#### Scenario: Unknown elevator
- **WHEN** `POST /api/elevators/{id}/report` targets an id that does not exist
- **THEN** the system returns `404` with `{"detail": "Elevator not found"}` and no row is written to `visit_reports`

#### Scenario: Invalid body
- **WHEN** the request body is missing required fields (e.g. `technician_name`)
- **THEN** the system returns FastAPI's default `422` validation error and no row is written to `visit_reports`
