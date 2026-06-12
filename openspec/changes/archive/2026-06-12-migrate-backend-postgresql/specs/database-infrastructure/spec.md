# database-infrastructure

## ADDED Requirements

### Requirement: Schema is managed exclusively by Alembic
The system SHALL apply all database schema changes through Alembic migrations. `Base.metadata.create_all()` SHALL NOT be used in any environment. The initial migration SHALL create the `elevators`, `elevator_features`, `elevator_trend_points`, and `visit_reports` tables.

#### Scenario: Clean stack startup
- **WHEN** `docker compose up` runs from a clean state
- **THEN** the `db` service becomes healthy, the `migrate` service applies `alembic upgrade head` successfully, and only then does the backend start and report healthy

#### Scenario: Database not ready
- **WHEN** the database container is not yet healthy
- **THEN** neither the `migrate` service nor the backend starts (gated by the compose healthcheck)

### Requirement: Seeding is deterministic and idempotent
The system SHALL seed an empty database with the existing deterministic 100-elevator dataset (seed 42), and SHALL NOT duplicate or modify data when the seed runs against an already-seeded database.

#### Scenario: First run seeds the fleet
- **WHEN** the backend starts against an empty (migrated) database
- **THEN** the `elevators` table contains 100 rows, each with exactly 3 feature rows and 6 trend point rows

#### Scenario: Subsequent runs do not duplicate
- **WHEN** the stack is restarted after a successful seed
- **THEN** row counts are unchanged and previously written data (e.g. visit reports) is intact

### Requirement: Configuration comes from the environment
The system SHALL read the database connection from the `DATABASE_URL` environment variable. Credentials SHALL NOT be hardcoded in application code or logged.

#### Scenario: Backend connects via environment configuration
- **WHEN** the backend starts in Docker Compose
- **THEN** it connects using the `DATABASE_URL` provided by the compose environment

#### Scenario: Credentials never appear in logs
- **WHEN** the backend logs startup and request activity
- **THEN** no database password appears in any log output

### Requirement: Tests run against a dedicated test database
The test suite SHALL use a dedicated test database, never the development database. Unit tests SHALL mock repositories; integration tests SHALL use httpx against the test database.

#### Scenario: Test suite isolation
- **WHEN** the full test suite runs
- **THEN** all tests pass using the test database and the development database state is untouched

#### Scenario: Test database unavailable
- **WHEN** the test database is not reachable
- **THEN** integration tests fail with a clear connection error instead of silently falling back to the development database
