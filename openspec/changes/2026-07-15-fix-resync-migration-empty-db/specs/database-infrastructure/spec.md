# Spec Delta: database-infrastructure

## MODIFIED Requirements

### Requirement: Seeding is deterministic and idempotent
The system SHALL seed an empty database with the existing deterministic 100-elevator dataset
(seed 42), and SHALL NOT duplicate or modify data when the seed runs against an already-seeded
database. Seeding SHALL be performed exclusively by `seed_database()` at backend startup; Alembic
data migrations SHALL NOT insert `elevators` rows. Any data migration that resyncs rows derived
from an elevator (e.g. `elevator_features`, `elevator_trend_points`) SHALL only modify rows whose
parent `elevators` row already exists, so it is a safe no-op against an empty database.

#### Scenario: First run seeds the fleet
- **WHEN** the backend starts against an empty (migrated) database
- **THEN** the `elevators` table contains 100 rows, each with exactly 3 feature rows and 6 trend point rows

#### Scenario: Subsequent runs do not duplicate
- **WHEN** the stack is restarted after a successful seed
- **THEN** row counts are unchanged and previously written data (e.g. visit reports) is intact

#### Scenario: Resync migrations are a no-op on an empty database
- **WHEN** `alembic upgrade head` runs against a freshly created, empty database (no elevator rows)
- **THEN** every data migration that resyncs elevator-derived rows matches zero parent rows and inserts nothing
- **AND** the upgrade completes without a foreign-key violation
- **AND** the `elevators`, `elevator_features`, and `elevator_trend_points` tables remain empty until `seed_database()` runs at backend startup
