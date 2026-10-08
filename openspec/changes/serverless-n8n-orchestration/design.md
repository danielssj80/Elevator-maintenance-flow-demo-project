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
- AWS resources are declared in Terraform in the repository; `terraform plan` shows drift and an empty plan after apply.

**Non-Goals:**
- Trend honesty: the derived-data wipe and the 6-day cap. For six days the trend mixes pre-calculated and live points. This is a backlog item.
- Reporting out-of-scope lifts as "no prediction".
- Natural-language scenarios (separate M5 task).
- n8n `/metrics` in production, an orchestration dashboard over production traces, and production metrics and logs export.
- A hosted editor or a persistent execution history.
- Managing the pre-existing resources (EC2, instance role, OIDC deploy role, Bedrock policy, Route 53) in Terraform. They are referenced as data sources; importing them is a separate backlog task.
- `terraform plan`/`apply` in CI. Apply stays a deliberate local step; CI runs `fmt -check` and `validate` only, which need no AWS credentials.
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
**Deadline.** The bootstrap passes the Runtime API's `Lambda-Runtime-Deadline-Ms` to the handler. The readiness wait and the webhook call (an `AbortSignal` timeout) end early enough to leave a 25 s stop reserve: the 20 s stop deadline plus margin. A slow Bedrock call then ends as a failed invocation with a graceful stop, not as a Lambda timeout that kills n8n before its spans are exported. A forced stop is reported as `spansFlushed: false`.

**No retries at either layer.** The scheduler invokes asynchronously, so Lambda's own async retry policy (default 2 retries, events kept 6 h) applies on top of the schedule's. Terraform declares the function's event-invoke config: 0 retries and a 900 s maximum event age.

Function settings: 2048 MB, 120 s timeout (worst measured run ×4), no VPC, reserved concurrency 1 where the account quota allows it. A new account's concurrency quota is 10, all of which must stay unreserved, and AWS then refuses the reservation. The script warns and continues: parallel invocations run in separate sandboxes, each with its own `/tmp` and n8n, so an overlap costs GB-s but corrupts nothing (ingest is idempotent and inference runs are atomic and non-overlapping in the backend).

### D3 — Webhook Trigger beside the existing triggers; Schedule disabled only in the image
Each workflow gains `Webhook` (POST, path = workflow slug, respond with the last node's output) wired to the same first node as the Schedule Trigger. The repository JSON keeps the Schedule enabled for local use, and the image build disables it (D1).

A test asserts both invariants:
- the repository definitions keep their Schedule enabled and have exactly one webhook;
- inside the image, every Schedule is disabled.

The local webhook is reachable on the developer's n8n at `:5678/webhook/<slug>`, which is harmless: the stack is local and the write endpoints are still token-guarded.

### D4 — Backend address fixed at build; execution identity via an expression
- **URLs.** The repository definitions keep the literal local address `http://backend:8000/api/...`. The image's seed stage (`orchestrator/seed/prepare-workflows.mjs`) rewrites it to the build argument `ELEVATOR_API_BASE_URL`, which defaults to `https://elevator.dsaavedra.dev`. It fails the build on any HTTP node whose URL does not start with the local address.
  - *Rejected, after the independent review:* reading `$env.ELEVATOR_API_BASE_URL` at run time. It works with `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` (verified in 2.37.6), but lifting that block lets any expression or Code node read the whole process environment. In the Lambda that environment holds the ingest token, the OTLP auth header and the AWS session, and the workflow output is logged. `$env` stays blocked everywhere.
- **Execution id.** The `X-N8N-Execution-Id` header becomes `={{ $('Webhook').isExecuted ? $('Webhook').first().json.body.invocationId : $execution.id }}`, so production sends the Lambda request id and local runs keep n8n's id. This needs no environment access.

Verified against the running image before relying on it (memory: read the running image, not the docs).

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

### D8 — Infrastructure in Terraform; secret values in two scripts
*Decision revised with the user on 2026-10-08, before any resource existed.* The first version used idempotent AWS CLI scripts. The independent review found several defects in their own describe/create/update logic. The tier is about 20 interdependent resources, and drift detection, an honest plan and a clean destroy are what Terraform provides and the scripts had to re-implement.

**Layout.** `infra/terraform/`, one root module, AWS provider pinned, Terraform ≥ 1.10:
- `backend.tf` (S3 backend), `providers.tf`, `variables.tf`, `data.tf` (existing resources), `ecr.tf`, `iam.tf`, `ssm.tf`, `lambda.tf`, `scheduler.tf`, `alarms.tf`, `outputs.tf`.

**State.** S3 bucket `elevator-tfstate-150911080650` in `eu-north-1`:
- created by hand once (bootstrap: Terraform cannot store its state in a bucket it creates);
- public access blocked, versioned, SSE-S3, TLS-only bucket policy;
- `use_lockfile = true` (S3-native locking, no DynamoDB).

**Existing resources, referenced only** (data sources): the EC2 instance, `elevator-ssm-role`, `github-actions-deploy`, `ElevatorBedrockInvokeNova`. Terraform attaches its own new policies to the two roles (`aws_iam_role_policy_attachment`) but never manages the roles themselves.

**Policies.** The JSON documents under `deploy/aws/policies/` stay the single source, loaded with `templatefile()`, so `test_aws_policies.py` keeps asserting exactly what is applied.

**What Terraform must not own:**
- *Secret values.* Anything Terraform manages is stored in the state in clear. `aws_ssm_parameter` resources are created with a placeholder and `lifecycle { ignore_changes = [value] }`; `30-ssm.sh` writes the real values, and the token is generated there. No secret value is ever in the state or the plan.
- *The function image.* CI moves `image_uri` on every merge (`lambda-images.yml`); Terraform declares the function and `ignore_changes = [image_uri]`.
- *The host env file.* `70-host-env.sh` (SSM Run Command, read on the instance).

**Bootstrap order.** A function can only be created from an image already in ECR:
1. `terraform apply -target=aws_ecr_repository.this` creates the repositories;
2. `deploy/aws/push-bootstrap-images.sh` builds both images (no attestations) and pushes them tagged with the current commit;
3. a full `terraform apply -var image_tag=<sha>`.

**Settings carried over unchanged:**
- reserved concurrency 1 for the orchestrator is variable-gated (default off), because a new account's quota refuses it;
- the async event-invoke config: 0 retries, 900 s maximum event age;
- schedules created `DISABLED` through a variable `schedules_enabled` (default false). The cutover is `terraform apply -var schedules_enabled=true`, which also turns on the silence alarms' actions (same variable).

**Validation.** CI runs `terraform fmt -check` and `terraform validate` (with `-backend=false`, no credentials). Locally, `terraform plan` before every apply; after an apply, a second plan must be empty.

### D9 — GB-s alarm by metric math, per day
CloudWatch has no GB-s metric. The alarm's expression is:

`SUM(Duration)/1000 × memoryGB`, per function, summed, over a 1-day period.

The threshold is 70 % × 400,000 / 30 ≈ 9,333 GB-s per day.

**Other alarms:**
- **Errors.** `Errors > 0`, per function, 1-hour period. Missing data is treated as not breaching, because there are no errors when nothing runs.
- **Missed daily run.** `Invocations` cannot tell the workflows apart: ingest every 30 minutes would keep it above zero forever. The handler therefore emits one CloudWatch Embedded Metric Format line per finished run (`Elevator/Orchestrator` · `WorkflowSucceeded`, `WorkflowDegraded`, dimension `Workflow`). The alarm fires when `WorkflowSucceeded{Workflow=daily-inference-and-digest}` is < 1 in each of 26 hourly periods, with missing data treated as **breaching**. A schedule that silently stops then raises an alarm instead of going quiet.
- **Ingest silence.** The same metric with `Workflow=telemetry-ingest`, < 1 in each of 2 hourly periods, missing data breaching. Ingest every 30 minutes is the main production feature, and the error alarms cannot see a schedule that stopped.
- **Silence alarms notify only while scheduled.** Both silence alarms have `actions_enabled = var.schedules_enabled`, so the time between provisioning and cutover sends no alarm emails.
- **Evaluation length.** 26 × 1 h = 93,600 s exceeds a day. PutMetricAlarm allows up to 7 days for periods of an hour or more. This is verified at provisioning: `terraform apply` fails loudly if AWS refuses, and the fallback is 13 × 2 h.
- **Degraded runs.** `WorkflowDegraded` (an agent node failed and the run continued, e.g. no digest) is recorded but does not page. It is visible on the metric and in the log line.

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
- builds with `docker build --provenance=false --sbom=false`. Lambda accepts a single image manifest, and BuildKit wraps the image in an index whenever it attaches attestations. Docker 29 with the containerd store does that even for a plain `docker build`: verified locally, the descriptor is `vnd.oci.image.index.v1+json` without the flags and a single `vnd.oci.image.manifest.v1+json` with them. `deploy/aws/push-bootstrap-images.sh` uses the same flags;
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

Production checks that need the new backend can only run **after** the merge: until then production runs `main`'s backend (no Lambda transport) and `main`'s compose (no `INFERENCE_LAMBDA_FUNCTION`). The order is therefore provision, merge with schedules disabled, verify, then enable.

1. **Provision (user's go-ahead).**
   - The user creates the state bucket by hand (D8).
   - `terraform init`, then the bootstrap order: ECR → push images → full `plan` reviewed → `apply`. Schedules are disabled and the silence alarms have no actions.
   - `30-ssm.sh` writes the secret values; `70-host-env.sh` writes the host env file.
   - A second `terraform plan` is empty.
   - After `70-host-env.sh` the backend on `main` holds the token, so the ingest and inference routes are registered behind it.
   - Inference answers 503 until the merge, because `main` has no scorer transport. Only token holders can see that.
2. **Pre-merge checks** (only what `main` supports):
   - invoke `elevator-scorer` directly with the golden rows;
   - invoke `elevator-orchestrator` with `telemetry-ingest` and check that readings are stored in production;
   - read the backend's startup log line on the host.
3. **Merge** (user's approval).
   - The application deploy brings the Lambda transport and trace export.
   - `lambda-images.yml` publishes both images and points the functions at the merge commit.
4. **Post-merge checks:**
   - a production `POST /api/inference/run` with the token → 200;
   - the orchestrator with each workflow;
   - one trace in Grafana Cloud: n8n → backend → scorer → Postgres;
   - the failure checks.
5. **Cutover.** `terraform apply -var schedules_enabled=true`, which also turns on the silence alarms' actions. Observe for 48 h, then extrapolate GB-s to a month.

**Rollback:**
- `terraform apply -var schedules_enabled=false` stops all scheduled work.
- Removing `TELEMETRY_INGEST_TOKEN` from `/etc/elevator/.env` and restarting the backend returns production to 404 on the ingest and inference endpoints.
- Neither rollback touches the host's services.

## Open Questions

- The email address for the SNS alarm subscription is a value the user provides at provisioning time. It is not committed.
