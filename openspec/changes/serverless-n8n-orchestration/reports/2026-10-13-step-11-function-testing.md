# Step 11 Report — Endpoint and Function Testing (AWS)

- Date: 2026-10-13
- Change: serverless-n8n-orchestration
- Account 150911080650, eu-north-1. Terraform state in `elevator-tfstate-150911080650`.

## Provisioning (11.2)
- Plan reviewed with the user: 36 to add, 0 to change, 0 to destroy. Apply in the bootstrap order: ECR (2) → images `ec9f785` → `30-ssm.sh --from-dotenv` (Grafana credentials checked first: HTTP 200) → 34 added.
- Second plan: **No changes**. State scan: 0 `aws_ssm_parameter`, 0 Basic-auth, 0 `glc_`, 0 AWS keys.
- 26 × 1 h silence alarm accepted by AWS (review Q1 closed). The ECR repository policy is declared (review Q2 closed): CI's `UpdateFunctionCode` succeeded at e815bc2.
- `70-host-env.sh`: 3 of 3 entries written, `/etc/elevator/.env` 600 root, backend recreated, startup log clean. Ingest and inference routes went from 404 to **401** without the token.

## Pre-merge checks
- Scorer invoked directly with the 70 golden rows: equal to the expected scores, model `8fbb94ff07b7`; unknown operation → client error, no function error.
- From the production backend container: identity `elevator-ssm-role` (IMDS), scorer `model` → 200.
- Orchestrator `telemetry-ingest` → 70 readings in production (70 lifts, source `n8n-telemetry-ingest`), 906 MB peak, 34.4 s billed (cold), EMF `WorkflowSucceeded=1`, trace in Grafana Cloud (`n8n-lambda` / `workflow.execute`).

## Found only in AWS (fixed, each now under a test)
| Symptom | Cause | Fix |
|---|---|---|
| `EACCES … /tmp/n8n-home/.n8n` | Lambda runs the image as its own user; n8n's seed config is 0600 | seed `a+rX` (no secret in it); image test as uid 993 |
| `EMFILE: too many open files` | Lambda's fixed 1024-fd limit; n8n opens the editor UI's assets at start-up | `N8N_DISABLE_UI=true` (ready even at 256 fds); image test under `nofile=1024` |
| `AccessDenied … user/certbot-route53` on the host | the host's root `~/.aws` (certbot DNS-01 keys) outranks the instance role | `70-host-env.sh` reads SSM with the credential files ignored |
| `error storing credentials` on `docker login` | Docker Desktop's Windows credential store rejects the ECR token | throwaway `DOCKER_CONFIG` for login and push |
| merge of #39 started no build and no Lambda publish | GitHub delivered no push event | #40: `workflow_dispatch` on both image workflows; the next push ran everything |
| `UnsupportedImageLayerDetected` on the orchestrator update from CI | n8n base ships zstd layers; the runner's classic Docker labelled them gzip | #41: buildx with `compression=gzip,force-compression=true`; 15/15 layers verified gzip |

## Post-merge (11.3–11.5)
- Both functions on the merge SHA `e815bc2`, published by CI (`LastUpdateStatus: Successful`).
- Production backend and frontend images: `a3f45d9` and later (code of #39).
- Non-persisting scoring in the production backend: `LambdaInferenceClient`, 3 golden rows equal, model `8fbb94ff07b7`, nothing written; trace `7a23ad9c39d6c13df6e4fa9f9be1ea77`.
- Orchestrator `telemetry-ingest` on the CI image: 70 accepted, 19.5 s (warm), `spansFlushed: true`; backend trace id `68d1e326e0f5e9b5eca2df17ebdf37bc`.
- Error-alarm chain proven by a real failure: `elevator-orchestrator-errors` OK → ALARM at 16:59 (EMFILE invocation), SNS action executed, back to OK at 18:05.
- No persisted inference before cutover (user decision): the first persisted re-score is the 06:00 schedule.

## Cutover (15.3, started)
- 2026-10-13 18:29 UTC: plan 0/4/0 (two schedules ENABLED, two silence alarms actions on), applied. `elevator-ingest-missing` OK; `elevator-daily-run-missing` ALARM until the first daily run (no notification on enabling).
- Pending: 48 h observation, GB-s extrapolation, then archive.

## Outcome
PASS, with the 48 h observation outstanding.
