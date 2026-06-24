# Step 3 Report — Verification

- Date: 2026-06-24
- Change: cloud-dev-workflow

## Scope Note
Infrastructure/docs-only change. New source: `scripts/dev-setup.sh` (Bash) plus
docs (`docs/dev-workflow.md`, `docs/base-standards.md` reference) and the carried
`CLAUDE.md` §7 edit. No backend/frontend application code, no DB schema, no API
surface. Therefore:
- Step 4 (review existing tests): no tests are affected — none required updating.
- The backend unit suite is run purely as a regression sanity baseline.
- Step 5 (E2E Playwright): not applicable — no frontend change.

## Commands Executed

### 3.1 / 3.2 — `scripts/dev-setup.sh` (run + idempotent re-run)
```
bash scripts/dev-setup.sh
```
- First run: pulled `postgres:16-alpine` and built `backend`, `migrate`, `frontend`
  images. (The very first invocation's tool output was lost, but the images were
  confirmed present: `docker images` showed all four.)
- Re-run: completed with **exit 0**, cache-hit, printed the "done — no services
  started" message. Confirms **idempotency** and that the script starts no services.

### 3.3 — Backend unit suite in Docker
```
docker-compose up -d db                  # healthy
docker exec <db> createdb -U user elevator_test_db   # already existed
docker run --rm --network elevator-maintenance-flow-demo-project_default \
  -v "$PWD/backend":/app -w /app \
  -e TEST_DATABASE_URL="postgresql+asyncpg://user:password@db:5432/elevator_test_db" \
  elevator-maintenance-flow-demo-project-backend:latest \
  sh -c "pip install -q -r requirements-dev.txt && python -m pytest tests/unit/ -q"
```

## Results
- `scripts/dev-setup.sh`: exit 0 (first run images built; re-run idempotent, exit 0).
- Backend unit suite: **22 passed, 0 failed, 0 skipped** (1.48s).

## DB State
- `db` started healthy, test DB `elevator_test_db` already present; suite manages its
  own fixtures. `db` stopped after the run. No dev/production data touched.

## Notes
- The prod backend image ships without dev dependencies, so `pytest` was installed
  ephemerally for the run (same as prior changes; tracked by the backlog "dev Docker
  image" task). `scripts/dev-setup.sh` deliberately only prepares images; the test
  recipe lives in `docs/dev-workflow.md`.

## Adversarial-review fixes — re-verification (2026-06-24)
Two Majors were found and fixed, then re-verified:
- **Major 1 (Compose CLI portability)**: `scripts/dev-setup.sh` now auto-detects
  `docker compose` (v2) / `docker-compose` (v1). Re-run on this host: detected
  `docker-compose`, **exit 0**, images ready, no services started.
- **Major 2 (broken documented test command)**: the `docs/dev-workflow.md` recipe
  was using `$(basename "$PWD")` (capitalised) for the Compose network name, which
  does not match compose's lowercased project network. Fixed to a lowercased
  `PROJECT` and `${PROJECT}-backend:latest`. The corrected recipe was executed
  **verbatim**: `PROJECT=elevator-maintenance-flow-demo-project`, **22 passed,
  exit 0**.

## Live Claude Code web sandbox validation (2026-06-24)
A real web session on this branch was used to validate the cloud workflow. Findings
(cumulative, in the order hit):
1. **Docker daemon not auto-started** — `dockerd` starts as root; the cache keeps
   files, not processes, so it must be started per session.
2. **Setup-script CWD is not the repo root** — `bash scripts/dev-setup.sh` as the
   setup script → `exit 127`; the same command run interactively worked
   (`repo root = /home/user/Elevator-maintenance-flow-demo-project`). Absolute path
   required.
3. **`Trusted` network blocks Docker Hub's CDN** — `docker compose pull postgres:16-alpine`
   → `403` from `production.cloudfront.docker.com` (Trusted allows `cloudflare`, not
   `cloudfront`). **Full** unblocked the pull.
4. **The wall — image builds fail TLS** — with daemon up + Full, `docker compose build`
   failed: `pip install` inside the build container →
   `CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain` against
   pypi.org. The sandbox's MITM proxy CA is trusted on the host but not inside build
   containers. `npm ci` would hit the same.
5. **Non-Docker work confirmed** — host `python3 -m venv && pip install xgboost
   scikit-learn pandas` → `HOST-PIP-OK`.

`scripts/dev-setup.sh` itself behaved correctly in the sandbox (auto-detected
`docker compose` v2 — Major-1 fix validated live); the build failure was the proxy,
not the script.

**Decision**: adopt the two-track workflow. Track A (web) = non-Docker work (M1);
Track B (local / dev EC2) = the Docker stack and tests. The dev-EC2 backlog task is
elevated to a real dependency for the Docker loop.

## Outcome
PASS (two-track scope; Docker-in-sandbox proven impractical and moved out of scope)
