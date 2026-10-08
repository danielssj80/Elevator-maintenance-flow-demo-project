## Why

M5 shipped n8n orchestration on the local stack only. Close the laptop and nothing fires: production never ingests telemetry, never re-scores the fleet, and still serves the pre-calculated predictions (Notion: *Run the n8n orchestration tier in production*, change 2 of 2). Change 1 (`harden-production-write-gate`, PR #38) made it safe to open the ingest and inference endpoints in production behind a token. This change provides what calls them, and what scores the fleet once it is called.

Two constraints shape it:

- **The production host cannot take n8n.** The `t3.micro` (~916 MB) already runs PostgreSQL, the backend, the frontend and nginx. Measured in the spike, an n8n process peaks at ~960 MB.
- **The scorer is not in production either.** `POST /api/inference/run` calls the xgboost scoring service, which the production compose deliberately omits, so a production run today answers 503.

The decision taken with the user: run both as **AWS Lambda functions inside the free tier**. A local spike (branch `spike/n8n-lambda`) proved that n8n 2.37.6 runs under the Lambda Runtime Interface Emulator with only `/tmp` writable, executes a workflow through a webhook, and flushes its spans on shutdown. At 2048 MB an invocation takes 16–28 s, which is about 26 % of the free tier at the chosen cadence.

## What Changes

- **New orchestrator Lambda (`elevator-orchestrator`).**
  - **Image.** A container image built from the pinned `n8nio/n8n:2.37.6` with a small Node Runtime API loop. It is seeded at build time with both workflows, already imported and published, and with credential placeholders that carry no secret.
  - **Invocation.** Each invocation runs one workflow. The handler starts `n8n start`, waits for real readiness, calls that workflow's Webhook Trigger on localhost, then stops n8n and waits for it to exit so its spans are flushed.
  - **No persistent state.** No n8n database survives the invocation, and no editor runs in production.
- **Two EventBridge Scheduler schedules** invoke it: telemetry ingest every 30 minutes, and inference plus digest daily at 06:00 Europe/Madrid. Local cadences are unchanged.
- **Workflows changes.**
  - **Webhook Trigger.** Each workflow gains one beside its existing Schedule and Manual triggers, so one JSON serves local and production.
  - **Configurable base URL.** The backend address is no longer hard-coded to `http://backend:8000`.
  - **No Schedule Triggers in the Lambda image.** They are disabled in the seed, so only EventBridge decides when work runs.
- **New scorer Lambda (`elevator-scorer`).**
  - **Image.** The existing `inference/` scorer packaged as a container image with a Lambda handler. Scoring logic and the model are unchanged.
  - **Backend client.** The backend's inference client gains a Lambda transport, selected by configuration (`INFERENCE_LAMBDA_FUNCTION`). Production invokes the scorer with the instance role. Local keeps the HTTP service. Failures map to the same 503/502 contract.
- **Secrets live in SSM Parameter Store as SecureString parameters.** These are the ingest token and the Grafana Cloud OTLP credentials.
  - **Lambdas.** Read them at cold start.
  - **Production host.** Its env file is written from SSM by the provisioning script, never from the repository.
- **OTel goes straight to Grafana Cloud.**
  - **Sources.** The orchestrator, the scorer and the production backend all export there.
  - **Node spans.** Per-node spans are switched off at the source (`N8N_OTEL_TRACES_INCLUDE_NODE_SPANS=false`) instead of filtered in a Collector.
  - **Execution identity.** The Lambda request id replaces n8n's execution id, which is always `1` on a fresh database.
- **CI publishes both images to private ECR** (Lambda accepts neither GHCR nor ECR Public), SHA-tagged, and points each function at the new image.
- **AWS resources are declared in Terraform under `infra/terraform/`.** The state lives in a private, encrypted, versioned S3 bucket with S3-native locking (Terraform ≥ 1.10). That bucket is created once by hand, outside Terraform. Terraform declares:
  - two ECR repositories with lifecycle rules;
  - two functions with least-privilege roles, and the function event-invoke config (no async retries);
  - the schedules (created disabled) and their role;
  - the SSM parameters' existence and permissions, **not their values**;
  - the policy attachments on the existing instance and GitHub OIDC roles;
  - CloudWatch alarms for daily GB-s above 70 % of the free-tier pace, for any function error and for silent schedules, sent through SNS email.
- **Existing resources are referenced, not managed.** The EC2 instance, `elevator-ssm-role`, `github-actions-deploy`, `ElevatorBedrockInvokeNova` and Route 53 are read as data sources. Importing them is a separate backlog task.
- **Two scripts remain, for what must stay out of the Terraform state:**
  - `deploy/aws/30-ssm.sh` writes the secret values (the generated token; the Grafana values entered silently);
  - `deploy/aws/70-host-env.sh` writes the host env file from SSM on the instance.
- **BREAKING (spec):** *The orchestration tier is local-only and says so* is replaced, because production now runs scheduled work. The production compose still defines no orchestrator service, and the host gains no process.

## Capabilities

### New Capabilities

None. The serverless runtime belongs to the existing capabilities below.

### Modified Capabilities

- `workflow-orchestration` (main):
  - Requirements added: serverless execution of a workflow per invocation; production schedules; only webhook triggers fire in the Lambda; credentials injected at invocation from SSM; fail-fast on missing secrets; the image carries no secret.
  - Requirements modified: separate schedules (production cadence), one distributed trace (production identity and direct export), agent prompts not exported (node spans off at the source).
  - *Local-only* is replaced by a truthful statement of what runs where.
- `risk-inference`: the scorer can run as a Lambda function, and the backend reaches it by invocation when configured, with the existing failure contract.
- `deploy-pipeline`: CI publishes the orchestrator and scorer images to private ECR and updates both functions.
- `production-deployment`: scheduled ingest and daily scoring run in production; secrets come from SSM; the instance may invoke only the scorer; usage and failure alarms exist.
- `observability`: production exports traces directly to Grafana Cloud, and an unreachable endpoint never fails the work.

## Impact

- **New code:**
  - `orchestrator/`: Dockerfile, runtime bootstrap, handler, seed build.
  - `backend/inference/lambda_handler.py` and `backend/inference/Dockerfile.lambda`.
  - `backend/app/services/inference_client.py`: Lambda transport.
  - `infra/terraform/` (resources) and `deploy/aws/{30-ssm,70-host-env}.sh` (secret values).
- **Changed:**
  - `n8n/workflows/*.json`: Webhook Trigger, base URL, execution identity.
  - `.github/workflows/build-images.yml`: an ECR job.
  - `docker-compose.prod.yml`: OTel, `INFERENCE_LAMBDA_FUNCTION`.
  - `backend/app/core/config.py`.
- **Tests:** handler logic (Node, with no network), the backend Lambda transport, workflow-definition invariants, image invariants (no secrets, Schedule Triggers disabled), the scorer Lambda handler against the golden vectors, and prod compose. `test_prod_compose_defines_no_orchestrator` stays true and gets an updated rationale.
- **API:** no endpoint, schema or data-model change.
- **Docs:** `docs/orchestration.md`, `docs/deployment.md`, `n8n/workflows/README.md`, `docs/backend-standards.md` (inference transport).
- **AWS:** new billable-if-exceeded resources, all within the free tier at the planned cadence. They are created only with the user's explicit go-ahead.
- **Production behaviour:**
  - Once the token is provisioned and the schedules are enabled, readings arrive every 30 minutes and the fleet is re-scored daily.
  - For six days the trend mixes pre-calculated and live points. That is accepted and tracked in the backlog, and is out of scope here.
