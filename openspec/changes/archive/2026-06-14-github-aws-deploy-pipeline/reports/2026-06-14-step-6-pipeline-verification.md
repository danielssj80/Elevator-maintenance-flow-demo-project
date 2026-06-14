# Step 6 Report — End-to-End Pipeline Verification

- Date: 2026-06-14
- Change: github-aws-deploy-pipeline

## Trigger

- PR #4 merged to `main` at 2026-06-14T16:14:32Z (merge commit `fd2b953`).
- Workflow `deploy.yml` run `27504696400` triggered automatically by the push, completed `success` in 28s.

## Workflow Steps (all success)

| Step | Result |
|---|---|
| Configure AWS credentials (OIDC) | success — role assumed via OIDC, no static creds |
| Send deploy command via SSM | success |
| Wait for remote command and propagate result | success — SSM status `Success` |
| Smoke check | success |

## Remote Deploy Evidence (SSM stdout)

- Images rebuilt: `elevator-migrate`, `elevator-backend`, `elevator-frontend`.
- `elevator-db-1` reached `Healthy`; `elevator-migrate-1` started (Alembic migrations applied via the existing migrate service).
- All containers recreated and running.

## Production Verification

- `GET https://elevator.dsaavedra.dev/health` → 200 `{"status":"ok"}`
- `GET https://elevator.dsaavedra.dev/api/elevators` → 200, 100 elevators (first: ELV-001, risk 0.91)

## Security

- Deploy used GitHub OIDC + SSM Run Command — no SSH.
- Security group ingress: only TCP 80 and 443. Port 22 absent (SSH remains closed).

## Failure Propagation (6.4)

- Verified by design: the "Wait" step polls `get-command-invocation` and ends with `test "$STATUS" = "Success"`, so any non-`Success` SSM status exits non-zero and fails the job. Remote stdout/stderr are printed to the Actions log before the assertion. Not force-failed in production to avoid a deliberate broken deploy; logic confirmed in the run log.

## E2E Playwright (Step 7)

- Not applicable — no frontend/UI changes in this change.

## Post-review remediation

Adversarial review (2026-06-14) raised one actionable finding, fixed before archive:

- **Unguarded SSM log fetches** (`deploy.yml` "Wait" step): the two `get-command-invocation`
  calls that print remote stdout/stderr ran under `bash -eo pipefail` with no guard, so a
  transient SSM API error could have failed an otherwise-successful deploy. Both calls now
  end with `|| echo "(… unavailable)"`, leaving only the `test "$STATUS" = "Success"`
  assertion to decide the job result. Stays within the existing requirement
  "Deployment failures fail the workflow" (makes the status assertion authoritative).
  Re-validated with actionlint (exit 0).

Other review findings (version-asserting smoke check, exact `"ok"` grep) are deferred to a
backlog task; the `production-deployment` out-of-scope drift is resolved by the spec sync at archive.

## Outcome

PASS
