# elevator-persistence

## Purpose

Governs how elevator fleet data is stored in and served from PostgreSQL, including the full `ElevatorSummary` and `ElevatorDetail` API contracts and the business rule for deriving `risk_level` from `risk_score`.

## Requirements

### Requirement: Elevator fleet data is served from PostgreSQL
The system SHALL store all elevator data (scalar fields, the 3 risk features, and the 6-point risk trend) in PostgreSQL and serve every read endpoint from the database. No module SHALL import the in-memory data layer (`app.data`).

#### Scenario: Listing the fleet reads from the database
- **WHEN** `GET /api/elevators` is called
- **THEN** the system returns the 100 seeded elevators read from the `elevators` table, sorted by `risk_score` descending, with the same `ElevatorSummary` JSON shape as before the migration

#### Scenario: Data survives a container restart
- **WHEN** the backend and database containers are restarted after data has been written
- **THEN** subsequent reads return the same data as before the restart, without re-seeding or duplication

### Requirement: Elevator detail preserves the existing contract
The system SHALL return the full `ElevatorDetail` shape from the database, including exactly 3 `features` and a 6-element `trend` array whose last element equals `risk_score`.

#### Scenario: Fetching an existing elevator
- **WHEN** `GET /api/elevators/{id}` is called with a seeded id (e.g. `ELV-001`)
- **THEN** the response contains all detail fields, exactly 3 `features`, and a 6-element `trend` with `trend[5] == risk_score`

#### Scenario: Fetching an unknown elevator
- **WHEN** `GET /api/elevators/{id}` is called with an id that does not exist
- **THEN** the system returns `404` with body `{"detail": "Elevator not found"}`

### Requirement: Risk level is derived, never trusted from storage
The service layer SHALL derive `risk_level` from `risk_score` using the business rules (`> 0.80` high, `0.50–0.80` medium, `< 0.50` low) so the API never exposes a stale stored level.

#### Scenario: Risk level matches the score
- **WHEN** any elevator is returned by a read endpoint
- **THEN** its `risk_level` equals the level derived from its `risk_score` per the business rules

#### Scenario: Stored level diverges from the score
- **WHEN** the `risk_level` column value diverges from `risk_score` (e.g. manual DB edit)
- **THEN** the API response still reflects the level derived from `risk_score`
