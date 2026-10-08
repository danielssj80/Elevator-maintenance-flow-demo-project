## Context

**Today.**
- Production is one `t3.micro` running `db`, `migrate`, `backend`, `frontend` and `nginx`.
- The orchestration tier (n8n, two workflows) runs only on the developer's machine.
- Change 1 (`harden-production-write-gate`, merged as #38) made the ingest and inference routers registrable in production behind a ≥32-character token, fail-closed, and rate-limited at nginx. No token is provisioned yet, so production answers 404 on them.

**Two gaps.**
- **n8n cannot live on the host.** It peaked at ~960 MB in the spike.
- **No scorer in production.** `POST /api/inference/run` calls the xgboost scorer over HTTP (`INFERENCE_URL`), and production has no scorer.

**Decisions already taken with the user:**
- n8n runs in AWS Lambda, with the image in private ECR.
- Ingest every 30 minutes, inference daily.
- OTel goes straight to Grafana Cloud.
- No persistent n8n database; the editor stays local.
- The scorer runs as a **second Lambda**, not on the host.
- "We'll see how it goes": redesign if free-tier consumption becomes a problem.

**Spike evidence** (branch `spike/n8n-lambda`, `spikes/n8n-lambda/FINDINGS.md`, all measured under the Lambda RIE with the CPU capped like Lambda):
- **Feasibility.**
  - A ~35-line Node Runtime API loop works on top of `n8nio/n8n:2.37.6`.
  - The hardened image has no `apk`, so `aws-lambda-ric` cannot be installed.
  - The image runs with a read-only filesystem plus `/tmp`.
- **Seed database.** A SQLite database seeded at build time (`import:workflow` + `publish:workflow`) and copied to `/tmp` per invocation saves ~18 s against importing per invocation.
- **Duration and memory.**
  - 2048 MB: 16–28 s per invocation, peak ~960 MB.
  - 1024 MB: 45–66 s.
  - 768 MB is the floor; 512 MB fails.
- **Execution and shutdown.**
  - `n8n start` is required: `n8n execute` never loads the OTel module and cannot start from a Schedule Trigger.
  - Spans flush in `@OnShutdown`, so the handler must SIGTERM and await exit before returning.
- **Silent traps:**
  - `/healthz` lies.
  - Credential overwrite only fills empty fields.
  - A missing token still yields a "successful" execution.
  - The execution id is always `1`.
  - A failed invocation can leave n8n alive in the reused sandbox.

**Scorer measured on 2026-10-08:** 134 MiB RSS idle and while scoring 100 rows; the image is 1.37 GB.

## Goals / Non-Goals

**Goals:**
- Production ingests every 30 minutes and re-scores daily with no developer machine running, and the host gains no process.
- One workflow definition serves local and production.
- Every secret lives in SSM. No image, workflow or repository file carries one.
- One trace per production execution in Grafana Cloud: n8n → backend → scorer → Postgres.
- Stay inside the Lambda free tier, with an alarm that fires well before it is spent.
- AWS resources are reproducible from scripts in the repository.

**Non-Goals:**
- Trend honesty: the derived-data wipe and the 6-day cap. For six days the trend mixes pre-calculated and live points. This is a backlog item.
- Reporting out-of-scope lifts as "no prediction".
- Natural-language scenarios (separate M5 task).
- n8n `/metrics` in production, an orchestration dashboard over production traces, and production metrics and logs export.
- A hosted editor or a persistent execution history.
- Infrastructure-as-code tooling (Terraform or CDK). Scripts are enough for two functions and are what the repository already does.
- Any frontend change. The dashboard reads the same API, and the frontend service-layer pattern (pages → services → fetch) is untouched.
- Any API, schema or data-model change. The backend change stays inside `services/` (the inference client) and `core/config.py`. Routers and repositories are untouched, which preserves the three-layer rule.

## Decisions

### D1 — Orchestrator image: n8n base + Node Runtime API loop + seed database
`orchestrator/Dockerfile`, multi-stage on `n8nio/n8n:2.37.6`:

1. **Seed stage.**
   - Copy `n8n/workflows/*.json`.
   - Disable every `n8n-nodes-base.scheduleTrigger` node with a build-time `node` script (D3).
   - Import the workflows and credential placeholders with empty secret fields.
   - Publish both workflows into `/opt/n8n-seed`.
2. **Final stage.**
   - Copy the seed, `runtime/bootstrap.mjs` and `runtime/handler.mjs`.
   - `ENTRYPOINT ["node", "/opt/runtime/bootstrap.mjs"]`.

**Environment** (non-secret, baked into the image):
- `N8N_USER_FOLDER=/tmp/n8n-home`, `N8N_SEED_FOLDER=/opt/n8n-seed`, `DB_TYPE=sqlite`;
- diagnostics, personalization and version notifications off;
- `N8N_ENABLED_MODULES=otel`, `N8N_OTEL_ENABLED=true`, `N8N_OTEL_TRACES_PRODUCTION_ONLY=true`, `N8N_OTEL_TRACES_INCLUDE_NODE_SPANS=false`;
- `N8N_OTEL_EXPORTER_SERVICE_NAME=n8n-lambda`;
- agent input/output recording off.

**`N8N_ENCRYPTION_KEY` is not set.** The seed's `.n8n/config` carries the key generated at build. That key encrypts only empty placeholders, so it protects nothing and reveals nothing.

**Logic split.** The handler logic is split into pure functions (`resolveWorkflow`, `buildCredentialOverwrite`, `isRealWebhookResponse`, `waitForReadiness`) so that Node's built-in `node:test` can cover them without Docker or network.

*Alternatives:*
- *Import per invocation:* +18 s per run, roughly +50 % GB-s. Rejected.
- *`n8n execute`:* no OTel module loaded. Rejected.
- *AWS base image + n8n via npm:* a ~1 GB install to maintain and a different n8n than the one used locally. Rejected.

### D2 — Handler sequence and failure discipline
```
validate event.workflow ∈ {telemetry-ingest, daily-inference-and-digest}   → else fail, nothing started
read secrets (cached per sandbox): ingest token, Grafana OTLP auth          → missing/empty → fail naming the parameter
build CREDENTIALS_OVERWRITE_DATA (ingest token header + AWS creds from role env incl. session token)
rm -rf /tmp/n8n-home; cp -r seed → /tmp/n8n-home
spawn `n8n start` with that env
try:
  poll /healthz/readiness until 200 + JSON (deadline 60 s; abort if the child exits)
  POST /webhook/<workflow> with {"invocationId": <Lambda request id>}; retry only on 404 (webhook not yet registered)
  require HTTP 200 + application/json; else fail
finally:
  SIGTERM; await exit (deadline 20 s, then SIGKILL and report spans lost)
log the workflow's final output (digest) and timings; return them
```
Function settings: 2048 MB, 120 s timeout (worst measured run ×4), no VPC, reserved concurrency 1. With reserved concurrency of 1, the two schedules can never run concurrently. A throttled schedule shows up as an error-alarm candidate rather than a parallel run.

### D3 — Webhook Trigger beside the existing triggers; Schedule disabled only in the image
Each workflow gains `Webhook` (POST, path = workflow slug, respond with the last node's output) wired to the same first node as the Schedule Trigger. The repository JSON keeps the Schedule enabled for local use, and the image build disables it (D1).

A test asserts both invariants:
- the repository definitions keep their Schedule enabled and have exactly one webhook;
- inside the image, every Schedule is disabled.

The local webhook is reachable on the developer's n8n at `:5678/webhook/<slug>`, which is harmless: the stack is local and the write endpoints are still token-guarded.

### D4 — Backend address and execution identity via expressions
- **URLs.** HTTP node URLs become `={{ $env.ELEVATOR_API_BASE_URL || 'http://backend:8000' }}/api/...`.
  - n8n 2.x blocks `$env` in expressions by default (`N8N_BLOCK_ENV_ACCESS_IN_NODE`). The Lambda image and the local compose both set it to `false`, so the definitions are identical in both places.
  - If the running image refuses this despite the flag, the fallback is a build-time substitution of the literal URL in the seed stage, with the same test.
- **Execution id.** The `X-N8N-Execution-Id` header becomes `={{ $('Webhook').isExecuted ? $('Webhook').first().json.body.invocationId : $execution.id }}`, so production sends the Lambda request id and local runs keep n8n's id.

Both expressions get verified against the running image before they are relied on (memory: read the running image, not the docs).

### D5 — Scorer as a Lambda: same `Scorer`, new handler, AWS base image
- **Image.** `backend/inference/Dockerfile.lambda` is built `FROM public.ecr.aws/lambda/python:3.12`, which ships its own runtime client, plus `inference/requirements.txt` and the model.
- **Handler.** `inference/lambda_handler.py` loads `Scorer` once per sandbox and dispatches `operation`:
  - `model` → `{feature_names, model_version}`;
  - `score` → `{scores, contributions, model_version}`.
- **Errors.** A `FeatureOrderMismatch` or an unknown operation is **returned** as `{"error": {"type": "client", "detail": ...}}` with no exception. A Lambda function error is reserved for the unexpected, so the backend can tell a 4xx-equivalent from a crash.
- **Tracing.** The handler extracts W3C context from `event["trace_context"]`, opens `inference.score` with the same attributes as the HTTP route, and calls `force_flush()` before returning.
- **Settings.** 1024 MB, 30 s timeout. One run a day makes the cost negligible.

*Alternatives:*
- *Scorer container on the host:* the cheapest option, but rejected by the user so that the host gains no process.
- *Inside the orchestrator Lambda:* breaks the backend → scorer contract.

### D6 — Backend Lambda transport behind the existing client interface
**Client.** `InferenceClient` keeps its two methods (`score`, `feature_names`). `LambdaInferenceClient` implements the same two over `boto3` `lambda.invoke`, run in `asyncio.to_thread`, because the sync boto3 call would block the event loop. That is the same rule already applied to Bedrock.

**Selection.** A factory `get_inference_client()` returns the Lambda client when `settings.inference_lambda_function` is set, and the HTTP client otherwise. `InferenceService` is unchanged apart from how its client is obtained.

**Error mapping:**
| Condition | Result |
|---|---|
| `EndpointConnectionError`, `ConnectTimeoutError`, `ReadTimeoutError`, `ClientError` (throttling, `AccessDenied`, `ResourceNotFound`), `NoCredentialsError` | 503 "Inference service is unavailable" |
| response has `FunctionError` | 502 "Inference service returned a function error" |
| payload `{"error": {"type": "client"}}` | 502 with the detail, matching today's handling of a non-200 from the HTTP service |

**Tracing.** The trace context is injected into the payload. botocore instrumentation, already installed for Bedrock, produces the client span.

### D7 — Secrets: SSM is the source, read at cold start
**Parameters** (SecureString, default KMS key):
- `/elevator/orchestrator/ingest-token`
- `/elevator/otel/grafana-otlp-endpoint`
- `/elevator/otel/grafana-otlp-auth` (the `Authorization=Basic …` header value)

**Readers:**
- **Orchestrator.** The handler reads all three with the AWS SDK v3 SSM client, resolved from the n8n image's own `node_modules` if present, else bundled at build. It caches them per sandbox.
- **Scorer.** Reads only the two OTel parameters, with `boto3`, which is in the base image.
- **Host.** The provisioning script copies the token and the OTel values into `/etc/elevator/.env` through SSM Run Command. It never prints them and never writes them to disk locally.

**Rotation.** Rotating the token means re-running provisioning with `--rotate`, which updates SSM and the host env file and restarts the backend.

*Alternative rejected:* Lambda environment variables populated from SSM at deploy time. They are visible in the console and in `GetFunctionConfiguration`, and they drift from SSM.

### D8 — Infrastructure as idempotent scripts in `deploy/aws/`
**Scripts.** Each script is `set -euo pipefail`, describe-before-create, and safe to re-run:
- `00-env.sh` (names, region `eu-north-1`, account);
- `10-ecr.sh` (two repositories + lifecycle keep 3);
- `20-iam.sh` (two function roles, instance-role policy `ElevatorInvokeScorer`, deploy-role policy additions);
- `30-ssm.sh` (create the token if absent; prompt for the Grafana values; `--rotate`);
- `40-lambda.sh` (create or update the functions from the latest SHA in ECR);
- `50-schedules.sh` (Scheduler role + two schedules, Europe/Madrid, retries 0, created **disabled**);
- `60-alarms.sh` (SNS topic + email, metric-math GB-s alarm, error alarms, missed-daily-run alarm);
- `70-host-env.sh` (write the host env file entries via SSM Run Command, restart the backend).

**Cutover.** Schedules start disabled, so the cutover is a deliberate, separate step: `50-schedules.sh --enable`.

**Validation.** `shellcheck` runs in CI. A `--dry-run` flag prints every AWS call without executing it. That is the only way these scripts are exercised before the user approves real resource creation.

**Bootstrap order.** On the very first run, `40-lambda.sh` can only create the functions once an image exists, so it pushes an initial image with the local Docker build. After that, CI owns updates.

### D9 — GB-s alarm by metric math, per day
CloudWatch has no GB-s metric. The alarm's expression is:

`SUM(Duration)/1000 × memoryGB`, per function, summed, over a 1-day period.

The threshold is 70 % × 400,000 / 30 ≈ 9,333 GB-s per day.

**Other alarms:**
- **Errors.** `Errors > 0`, per function, 1-hour period. Missing data is treated as not breaching, because there are no errors when nothing runs.
- **Missed daily run.** The orchestrator's `Invocations` over 26 hours is < 1, with missing data treated as **breaching**. A schedule that silently stops then raises an alarm instead of going quiet.

### D10 — Production OTel: traces only, direct, best-effort
**Backend** (`docker-compose.prod.yml`):
- `OTEL_ENABLED=true` and `OTEL_SERVICE_NAME=elevator-backend`;
- the endpoint and `OTEL_EXPORTER_OTLP_HEADERS` from `/etc/elevator/.env`;
- new settings `OTEL_METRICS_ENABLED` and `OTEL_LOGS_ENABLED`, both default `true` so local is unchanged, set to `false` in production.

The SDK's OTLP exporters read `OTEL_EXPORTER_OTLP_HEADERS` from the environment when none are passed. This is verified against the installed SDK before relying on it.

**Failure handling.** A failed export is already logged and never raised, which is the existing requirement *Collector unreachable while telemetry is enabled*.

**Lambdas.** The n8n Lambda gets `N8N_OTEL_EXPORTER_OTLP_ENDPOINT` and `N8N_OTEL_EXPORTER_OTLP_HEADERS`, set by the handler in the child environment from SSM at invocation, never baked in.

### D11 — CI: a separate Lambda image workflow
A new workflow, `lambda-images.yml`, runs on every push to `main`. It is **not** a job inside `build-images.yml`: `deploy.yml` runs on that workflow's success, so a failing Lambda job there would block the application deploy. The new workflow has its own concurrency group. It:
- `permissions: id-token: write`;
- assumes `vars.AWS_DEPLOY_ROLE_ARN`;
- builds with the classic `docker build` (no buildx attestations: Lambda rejects an image index carrying provenance manifests);
- logs in to ECR;
- builds and pushes both images by SHA;
- calls `aws lambda update-function-code` on both;
- runs `aws lambda wait function-updated-v2` on both.

The workflow **fails** if the functions do not exist yet. A merge before provisioning should be loud, not silently skipped, and it no longer endangers the application deploy.

**Rollout order.** Merge happens only after provisioning, and with the user's approval.

## Risks / Trade-offs

- **Bedrock with session-token credentials was only desk-checked.**
  - *Mitigation:* the ingest workflow already degrades to a fixed scenario when the agent fails. The first live invocation verifies the real path, and the digest is the only output that depends on it fully.
- **Cold start dominates cost (15–25 s of each run).**
  - *Mitigation:* the 70 % alarm, and the documented levers: 1024 MB, a longer ingest cadence, or a different host.
- **GB-s depends on duration variance.** The worst measured run, ×1,490 per month, is about 167k GB-s, 42 % of the free tier, still under the alarm.
- **The first live trend is mixed** (pre-calculated + live) for six days. This is accepted and is in the backlog.
- **The Lambda egress IP varies**, so nginx's per-IP limit is per invocation. At 49 requests per day this is irrelevant, and the token is the actual guard.
- **The image is large (~1.5 GB).** That is fine for Lambda (10 GB limit) and costs about $0.10/month in ECR storage beyond the free 500 MB. Keeping 3 images per repository bounds it.
- **A Grafana Cloud outage** loses traces only. It is never a failed run (D10).

## Migration Plan

1. Merge nothing to `main` until steps 2–4 have been approved and run, because the Lambda image workflow fails loudly without functions (D11). The application deploy is unaffected either way.
2. With the user's go-ahead, run `deploy/aws/` scripts 10–40 and 60–70 against the account. Schedules stay disabled.
3. Invoke each function once by hand:
   - the scorer through a production `POST /api/inference/run` with the token;
   - the orchestrator with each workflow.

   Then verify the trace in Grafana Cloud and the data in production.
4. Merge the PR. CI publishes images and updates the functions.
5. `50-schedules.sh --enable`. Observe for 48 h, then extrapolate GB-s to a month.

**Rollback:**
- `50-schedules.sh --disable` stops all scheduled work.
- Removing `TELEMETRY_INGEST_TOKEN` from `/etc/elevator/.env` and restarting the backend returns production to 404 on the ingest and inference endpoints.
- Neither rollback touches the host's services.

## Open Questions

- The email address for the SNS alarm subscription is a value the user provides at provisioning time. It is not committed.
