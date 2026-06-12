# Delta Spec: database-infrastructure
# Change: deploy-aws-https

## What changes

Adds the production data persistence requirement: the PostgreSQL data volume MUST survive `docker compose down` in the production environment. No changes to schema management, seeding, configuration, or test isolation requirements.

---

## New Requirement: Production data persists across Compose restarts

The production Docker Compose configuration SHALL use a named Docker volume for the PostgreSQL data directory. An anonymous volume or bind mount SHALL NOT be used in production.

### Scenario: Data survives `docker compose down`

- **GIVEN** the production stack has been running and visit reports have been written
- **WHEN** `docker compose -f docker-compose.prod.yml down` is run and then `docker compose -f docker-compose.prod.yml up -d` is run
- **THEN** all elevator rows, features, trend points, and visit reports are intact

### Scenario: Named volume created on first start

- **WHEN** the production stack starts for the first time
- **THEN** Docker creates a named volume (e.g. `elevator_postgres_data_prod`) for the PostgreSQL data directory
- **AND** `docker volume ls` shows this volume
