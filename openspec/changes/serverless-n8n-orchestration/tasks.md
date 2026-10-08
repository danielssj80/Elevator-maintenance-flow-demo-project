# Tasks: serverless-n8n-orchestration

> Scope:
> - Backend (inference transport, config), the scorer Lambda, the orchestrator image and handler, workflow definitions, CI, and AWS scripts.
> - No frontend change, so the E2E step is not applicable. No DB schema change, so there is no Alembic step.
>
> Working rules:
> - Every guard gets its mutation run inline. Break it, watch the named test go red, restore it, and note the result on the task line.
> - **No AWS resource is created without the user's explicit go-ahead** (gate at 11.0). Everything before it runs locally: pytest, `node:test`, the Lambda RIE, and `--dry-run`.

## 0. Setup: Create Feature Branch (MANDATORY)

- [x] 0.1 Create branch `feature/serverless-n8n-orchestration` from `main`
- [x] 0.2 Verify branch: `git branch --show-current`

## 1. Backend: inference transport (TDD)

- [x] 1.1 Write failing tests for `LambdaInferenceClient`, with a stubbed boto3 client and no network:
  - `score` and `feature_names` round-trip;
  - each transport/authorisation error → 503 (`EndpointConnectionError`, `ReadTimeoutError`, `ClientError` throttling/AccessDenied/ResourceNotFound, `NoCredentialsError`);
  - `FunctionError` → 502;
  - client-error payload → 502 with detail;
  - the call runs off the event loop;
  - trace context is injected into the payload.
- [x] 1.2 Write failing tests for `get_inference_client()`:
  - Lambda client when `INFERENCE_LAMBDA_FUNCTION` is set;
  - HTTP client otherwise;
  - the HTTP path makes no boto3 call, and the Lambda path makes no HTTP call.
- [x] 1.3 Implement D6 (`app/services/inference_client.py`, `app/core/config.py`: `inference_lambda_function`), and wire the factory where `InferenceService` gets its client.
- [x] 1.4 Tests pass. Mutations, each expected red:
  - map `ClientError` to 502 → 3 failed;
  - map `FunctionError` to 503 → 1 failed;
  - call boto3 on the loop thread → 2 failed;
  - make the factory always return HTTP → 1 failed.
  - Extra mutations: drop the trace context → 1 failed; ignore the client-error result → 1 failed; router constructs `InferenceClient()` directly → 1 failed (test added for it).
- [x] 1.5 Existing `test_inference_client.py` / `test_inference_service.py` / concurrency tests still green; no test relied on the HTTP client being constructed directly. (69 passed across the four files)

## 2. Scorer Lambda (TDD)

- [x] 2.1 Write failing tests for `inference/lambda_handler.py` (`inference/tests/test_lambda_handler.py`, run in the scorer image: 23 passed with the golden tests):
  - `model` returns the booster's feature names and version;
  - `score` reproduces `golden_vectors.json`;
  - wrong column order → `{"error": {"type": "client"}}` naming the expected columns, with no exception;
  - unknown operation → client error naming `model`/`score`;
  - the scorer loads once per sandbox;
  - with trace context, the span's parent is the caller's;
  - `force_flush` is called;
  - an exporter that raises does not fail scoring.
- [x] 2.2 Implement D5 (`lambda_handler.py`, `Dockerfile.lambda`).
- [x] 2.3 Tests pass. Mutations, each expected red:
  - raise instead of returning the client error → 1 failed;
  - drop `force_flush` → 1 failed;
  - load the scorer per invocation (the counting test) → 1 failed.
  - Extra mutations: ignore the parent context → 1 failed; let a flush error propagate → 1 failed.
- [x] 2.4 Build `Dockerfile.lambda` and invoke it under the RIE with the golden vectors. Record cold start, duration and peak memory. — 1024 MB / 0.58 vCPU, read-only FS: cold `model` 1.9 s, warm `score` 15–35 ms (70 and 100 rows), peak ~150 MiB; golden scores match; wrong order and unknown operation come back as client errors with no function error. Image 1.93 GB.

## 3. Production OTel settings (TDD)

- [x] 3.1 Write failing tests for each switch (`test_telemetry_signal_switches.py`, fresh interpreter per case; 3 red before the change) (`OTEL_METRICS_ENABLED=false`, `OTEL_LOGS_ENABLED=false`): with the switch off, no exporter or provider is installed for that signal and traces are still installed. Both default to `true`.
- [x] 3.2 Verify against the installed SDK that `OTLPSpanExporter(endpoint=…)` reads `OTEL_EXPORTER_OTLP_HEADERS` from the environment; record the source lines. If it does not, pass the headers explicitly and test that. — Verified in `opentelemetry-exporter-otlp-proto-http` 1.44.0, `trace_exporter/__init__.py:111-114`: `self._headers = headers or parse_env_headers(environ.get(OTEL_EXPORTER_OTLP_TRACES_HEADERS, environ.get(OTEL_EXPORTER_OTLP_HEADERS, "")))`.
- [x] 3.3 Implement D10 in `app/core/telemetry.py` + `config.py`.
- [x] 3.4 Tests pass. Mutation: ignore the metrics switch → red (2 failed). Extra mutations: ignore the logs switch → 2 failed; never attach the handler → 1 failed. Existing `test_telemetry_spans.py` still green (33 passed together).

## 4. Workflow definitions

- [x] 4.1 Write failing repository tests (`test_workflow_definitions.py`; 8 red before the edit). Each workflow must:
  - have exactly one Webhook Trigger, with POST and path = slug, wired to the same node as its Schedule Trigger;
  - keep its Schedule Trigger enabled;
  - contain no literal backend host in any HTTP node URL;
  - send `X-N8N-Execution-Id` from the webhook's `invocationId` when present;
  - pass the existing secret/instance scrub checks.
- [x] 4.2 Verify in the running `n8nio/n8n:2.37.6` image that `$env` is readable with `N8N_BLOCK_ENV_ACCESS_IN_NODE=false`, and that the `$('Webhook').isExecuted` expression evaluates on both trigger paths. Record the result. If either fails, apply the D4 fallback. — Verified in `n8nio/n8n:2.37.6` (probe workflow, two webhooks into one Set node): with the flag `false`, `$env` resolves and `execId` is the posted `invocationId` on the Webhook path and n8n's id (`2`) on the other path; with the default (`true`) the execution fails with HTTP 500, loudly, not a fallback. No fallback needed.
- [x] 4.3 Edit both workflows in the local editor and export them with `scripts/export-n8n-workflow.sh`. Do not hand-edit node ids. — Done as a scripted JSON edit instead (one Webhook node per workflow with the next id in the file's existing deterministic sequence; URL and header changes on every HTTP node), then imported with `scripts/n8n-import-workflow.sh --activate` into the running local n8n to prove it loads and runs (4.5). No existing node id changed.
- [x] 4.4 `docker-compose.yml`: n8n services set `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` (and `ELEVATOR_API_BASE_URL` unset → default). The `test_dev_compose.py` invariants (main/worker identical) still hold.
- [x] 4.5 Run both workflows on the local stack via the Schedule/Manual trigger *and* via the webhook. Readings are stored, the run completes, and the trace is linked. — Webhook `telemetry-ingest` (`invocationId=local-req-0001`): 70 accepted, trace `1c0d7cc4…` holds n8n `workflow.execute` (mode `webhook`) → backend `GET /api/elevators` + `POST /api/telemetry/readings`, both with `n8n.execution.id=local-req-0001`. Webhook `daily-inference-and-digest`: digest returned as the webhook response (Bedrock reached). Scheduled ingest at 13:45 UTC: 70 readings, trace `085bdc03…` mode `trigger` with `n8n.execution.id=348` on n8n and on both backend spans.
- [x] 4.6 Tests pass. Mutations, each expected red:
  - delete one webhook;
  - hard-code `http://backend:8000`.
  - Both were red by construction: the 8 failures in 4.1 were these exact states (no webhook, literal host).

## 5. Orchestrator image and handler (TDD)

- [x] 5.1 Write failing `node:test` tests for the pure handler functions (`orchestrator/runtime/lib.test.mjs`, 17 tests):
  - `resolveWorkflow`: known slugs accepted; unknown refused before anything spawns.
  - `buildCredentialOverwrite`: header credential from the token; AWS credential including `sessionToken`; a missing or empty token throws naming the parameter, not the value.
  - `isRealWebhookResponse`: 200 + JSON → true; 200 + text/html "starting up" → false; 503 → false.
  - Readiness polling: rejects non-JSON 200; aborts when the child exits.
  - Lifecycle: stop is called on every failure path (fake child process).
- [x] 5.2 Implement `orchestrator/runtime/{bootstrap,handler,lib}.mjs` (D1, D2, D7), starting from the spike's code.
- [x] 5.3 Implement `orchestrator/Dockerfile` with the seed stage that disables the Schedule Triggers (D1, D3), plus the credential placeholders with empty secret fields.
- [x] 5.4 Write failing image tests (`orchestrator/tests/image.test.mjs` with `node:test` instead of pytest — the backend test container has no Docker; skipped unless `ORCHESTRATOR_IMAGE` is set, run in CI):
  - every seeded Schedule Trigger is disabled;
  - each workflow has one enabled webhook;
  - every placeholder secret field is empty;
  - a scan of the image filesystem and environment finds no token pattern, no `Authorization=Basic` and no `AKIA`.
- [x] 5.5 Tests pass. Mutations, each expected red:
  - leave one Schedule enabled → 1 failed (image rebuilt);
  - put a placeholder value in a secret field → 1 failed (image rebuilt);
  - drop the `finally` stop → 2 failed;
  - accept any 200 → 2 failed.
  - Extra mutations: blank-token check weakened → 2; readiness accepts HTML → 1; dead child ignored → 1; session token dropped from the overwrite → 1; `temporaryCredentials: false` in the placeholder → 1 (image); node spans on → 1 (image).
- [x] 5.6 Run the RIE end to end against the local stack (backend + scorer + Collector): — 2 GB / 1.17 vCPU, read-only rootfs, `/tmp` only, SSM served by a local stub via `AWS_ENDPOINT_URL_SSM`:
  - `telemetry-ingest`: 24.1 s, 70 accepted, `spansFlushed: true`, peak 894 MB; Tempo trace `f7630ef9…` = n8n-lambda `workflow.execute` only (no node spans, `n8n.execution.id` 1) → backend spans carrying the Lambda request id.
  - `daily-inference-and-digest` (warm sandbox): 24.1 s, re-score ran; digest agent failed on the stub's fake AWS keys and the run continued with `output.error` → handler now logs `degraded: true` for it. Peak 1,090 MB.
  - Third invocation in the same sandbox: 23.9 s, fresh n8n (no stale process).
  - Unknown workflow: 0.0 s error naming the accepted slugs. Found and fixed: the message quoted the previous invocation's n8n log (`logTail` now reset per invocation).
  - Token parameter absent (cold sandbox): 0.3 s error naming `/elevator/orchestrator/ingest-token`, no n8n process started.
  - GB-s: 24 s × 2 GB ≈ 48 GB-s per run × 1,470 runs/month ≈ 71k GB-s ≈ 18 % of the free tier.
  - Both workflows run. Readings are stored, or the fleet is re-scored.
  - Spans reach the Collector after return, with no node spans.
  - `X-N8N-Execution-Id` = request id.
  - A missing token fails before n8n starts.
  - Record duration and peak memory for each workflow.

## 6. CI

- [x] 6.1 Add the `lambda-images.yml` workflow (D11; separate from `build-images.yml` so it cannot block `deploy.yml`): OIDC, ECR login, build/push both images by SHA, `update-function-code` + `wait function-updated-v2`. Pin the action versions as the existing jobs do.
- [x] 6.2 Add CI checks: `node --test orchestrator/`, `shellcheck deploy/aws/*.sh`, and the image tests from 5.4. — `ci.yml` gains `orchestrator` (handler tests, image build, image tests, shellcheck) and `scorer` (scorer tests inside the Lambda image; reproduced locally: 23 passed). The shellcheck step goes green once task 7 adds the scripts.
- [x] 6.3 Write a static test that the workflow runs only on pushes to `main`, has `id-token: write`, references no long-lived AWS secret, updates and waits for both functions, and is not part of `build-images.yml`. — `test_lambda_images_workflow.py`: 5 red before the workflow existed, 5 green after.

## 7. AWS provisioning scripts (local, dry-run only)

- [x] 7.1 Write `deploy/aws/00-env.sh` … `70-host-env.sh` per D8/D9 with `--dry-run`, describe-before-create and no secret echo. — `lib.sh` (sourced) replaces `00-env.sh`. The EMF metric `WorkflowSucceeded` per workflow was added to the handler (TDD) because `Invocations` cannot tell the daily run from ingest; `70-host-env.sh` reads SSM on the host with the instance role, so values never transit a Run Command parameter.
- [x] 7.2 Write the IAM policy documents as JSON files under `deploy/aws/policies/`. Write a test that no policy has `"Resource": "*"` for lambda, ssm, ecr or bedrock actions, and that the instance policy names only the scorer ARN. — `test_aws_policies.py`, 12 tests; `ecr:GetAuthorizationToken` is the one documented `*` (no resource-level permission exists).
- [x] 7.3 `shellcheck` clean. A `--dry-run` of every script prints the expected calls (output captured in the step-11 report). — shellcheck v0.10.0 clean; 39 mutating calls printed. The dry run found three bugs, fixed: creation calls were silenced by `>/dev/null` (print now on stderr); `put K "$(get …)"` on the host would write an empty token if SSM failed (now assigned and checked); recreating the backend without `IMAGE_TAG` would pull `:latest` (now the deployed SHA). Reserved concurrency made best-effort (new-account quota).
- [x] 7.4 Mutation: give the instance policy a wildcard resource → the policy test goes red. (2 failed; extra: scorer granted the ingest token → 1 failed)

## 8. Production compose and docs-adjacent config

- [x] 8.1 Write failing tests in `test_dev_compose.py` / new prod tests for `docker-compose.prod.yml`:
  - the backend has `OTEL_ENABLED=true`, `OTEL_METRICS_ENABLED=false`, `OTEL_LOGS_ENABLED=false` and `INFERENCE_LAMBDA_FUNCTION=elevator-scorer`;
  - there is no OTLP header and no token literal in the file;
  - the service set is exactly `db`, `migrate`, `backend`, `frontend`, `nginx`.
  - (1 red before the compose change; the service-set test was already true.)
- [x] 8.2 Update `docker-compose.prod.yml`. Also gave the Lambda client its own `INFERENCE_LAMBDA_REGION` (default `eu-north-1`) instead of borrowing `BEDROCK_REGION`.
- [x] 8.3 Rewrite the rationale of `test_prod_compose_defines_no_orchestrator`; its assertion is unchanged.

## 9. Review and Update Existing Tests (MANDATORY)

- [x] 9.1 Review `test_dev_compose.py`, `test_inference_*`, `test_orchestration_context.py`, the observability tests, and the workflow scrub tests for assumptions invalidated by D3–D6 and D10 (docstrings included).
- [x] 9.2 Update the affected tests and docstrings. — Stale "production never has a scorer" statements rewritten in `config.py`, `inference/main.py` and `test_inference_client.py`; `test_prod_compose_defines_no_orchestrator` rationale rewritten in 8.3. `test_orchestration_context.py` and the telemetry tests make no claim this change invalidates. No assertion needed changing.

## 10. Unit Tests and DB State Verification (MANDATORY)

- [ ] 10.1 Capture the pre-test DB baseline (table counts in the test database).
- [ ] 10.2 Run the targeted tests: inference client, Lambda handler, telemetry settings, workflow definitions, compose, policies, and `node --test`.
- [ ] 10.3 Run the full backend suite + `ruff check .` the way CI does (Python 3.12, `postgres:16-alpine`).
- [ ] 10.4 Verify the post-test DB state matches the baseline.
- [ ] 10.5 Create report `openspec/changes/serverless-n8n-orchestration/reports/YYYY-MM-DD-step-10-unit-tests.md`.

## 11. Manual Endpoint and Function Testing (MANDATORY — AGENT MUST EXECUTE)

- [ ] 11.0 **Gate: ask the user for explicit go-ahead to create AWS resources.** Present the `--dry-run` output and the resource list. Stop here until they answer.
- [ ] 11.1 Local, before AWS. Backend in production mode with `INFERENCE_LAMBDA_FUNCTION` pointing at the scorer under the RIE through a local endpoint override. `POST /api/inference/run` with the token → 200 and scores changed. Scorer stopped → 503. Restore the DB.
- [ ] 11.2 After the go-ahead, run scripts 10–40 and 60–70 (schedules disabled), then confirm the SNS subscription with the user.
- [ ] 11.3 Production:
  - `POST /api/inference/run` with the token → 200, scores dated today.
  - Without the token → 401.
  - `GET /api/elevators` unchanged in shape.
  - Rate limit still 429 above the burst.
- [ ] 11.4 Invoke the orchestrator once per workflow. Readings are stored with source `n8n-telemetry-ingest`, the digest is in the log, and one trace in Grafana Cloud runs n8n → backend → scorer → Postgres with no node spans.
- [ ] 11.5 Failure checks:
  - Invoke with an unknown workflow → error, alarm fires.
  - Temporarily make the token parameter unreadable → error before n8n starts. Restore it.
- [ ] 11.6 Create report `reports/YYYY-MM-DD-step-11-function-testing.md`, with timings, GB-s per invocation and the monthly extrapolation.

## 12. E2E Testing with Playwright MCP

- [ ] 12.1 Not applicable: no frontend change. The production dashboard is checked in 11.3 through the API it reads.

## 13. Update Technical Documentation (MANDATORY)

- [ ] 13.1 `docs/orchestration.md`: what runs where; the Lambda lifecycle; the silent traps from the spike; cadences; how to run the webhook locally.
- [ ] 13.2 `docs/deployment.md`: the `deploy/aws/` scripts, bootstrap order, cutover, rollback, token rotation, alarms and free-tier levers.
- [ ] 13.3 `n8n/workflows/README.md`: Webhook Trigger, base-URL expression, the Schedule disabled only in the image.
- [ ] 13.4 `docs/backend-standards.md`: the inference transport selection and error mapping. `docs/api-spec.yml`: availability note (production now registers the routes and scores via Lambda); no schema change.
- [ ] 13.5 Notion: update the task "Run the n8n orchestration tier in production" with progress. Add a backlog task for trend honesty if one does not exist yet.

## 14. Independent Adversarial Review (MANDATORY)

- [ ] 14.1 Run `/adversarial-review` as a cold-start agent in an isolated worktree.
- [ ] 14.2 Fix every finding, rerun the evidence, and create report `reports/YYYY-MM-DD-step-14-adversarial-review.md`.

## 15. Cutover and Verification

- [ ] 15.1 Archive, commit and open the PR. **The merge needs the user's approval.**
- [ ] 15.2 After the merge: CI updates both functions to the merge SHA (verify the image URIs).
- [ ] 15.3 `50-schedules.sh --enable`. After 48 h: reading counts per lift ≈ 96, daily scores present on two consecutive days, no alarm, GB-s extrapolated to a month and recorded.
- [ ] 15.4 Notion: mark the task Done and update M5 on the project page.
