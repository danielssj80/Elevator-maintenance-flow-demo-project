# Step 6 Report — Clean-Stack Verification (original goal)

- Date: 2026-07-15
- Change: fix-resync-migration-empty-db

## Purpose

Prove the `database-infrastructure` "Clean stack startup" scenario the bug was breaking:
`docker compose up` from a genuinely clean state (no Postgres volume) must apply
`alembic upgrade head` successfully and bring the backend up healthy, with the fleet seeded.

## Commands Executed

```bash
docker compose down -v          # remove the postgres volume → clean state
docker compose up -d --build     # rebuild images (migration code is baked in) + start
```

## Results

### Service status
```
backend    Up (healthy)          exit 0
db         Up (healthy)          exit 0
frontend   Up                    exit 0
migrate    Exited (0)            exit 0   ← previously exit 1 (FK violation)
```

### migrate log (full chain applied, no error)
```
Running upgrade  -> 638e311fa8e1  (create tables)
Running upgrade 638e311fa8e1 -> 0aac4958720e  (resync)
Running upgrade 0aac4958720e -> 2c43876e02dd  (motor-life)
Running upgrade 2c43876e02dd -> 97f03bcd4e85  (add direction)
Running upgrade 97f03bcd4e85 -> 56cd241fcfd6  (celsius features)
Running upgrade 56cd241fcfd6 -> aa3f0fc81e9c  (nl_explanation °C)
```

### Endpoint checks (seeding populated by backend startup, as designed)
- `GET /api/elevators` → 200, **100 elevators** (top: ELV-073, risk `high`).
- `GET /api/elevators/ELV-001` → 200, **3 features** (each with a `direction`:
  increases/increases/decreases) and **6 trend points**.
- `GET /health` → 200 `{"status":"ok"}`.
- `GET http://localhost:3000` (frontend) → HTTP 200.

## Interpretation

- The migration chain is a correct no-op on the empty DB (no FK violation); `seed_database()`
  then populated 100 elevators, features (with `direction`), and trend points at backend
  startup — exactly the designed division of responsibility.
- The `direction` field being present confirms the add-direction migration + seed cooperate
  correctly on a fresh volume.

## Outcome

PASS
