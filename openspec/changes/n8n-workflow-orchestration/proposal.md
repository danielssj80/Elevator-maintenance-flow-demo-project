# Proposal: n8n-workflow-orchestration

## Why

Nothing in this system has a scheduler. `openspec/config.yaml` claims the model
"scores each elevator's failure probability **daily** from telemetry signals",
and after the previous two changes every piece of that sentence exists except
the word *daily*: there is an ingest endpoint with nothing posting to it, an
inference endpoint with nothing triggering it, and `app/core/metrics.py`'s
lifespan refresh loop carrying an honest comment calling itself "the app's only
scheduler". Re-scoring has been done by hand, with `curl`.

The observability work is likewise waiting on a producer.
`observability/grafana/dashboards/orchestration.json` already ships with a text
panel reading **"Not wired up yet"** and three queries against
`n8n_queue_jobs_waiting`, `n8n_queue_jobs_active` and
`n8n_workflow_executions_total` that nothing answers. The
`elevator-backend → inference → postgresql` trace exists; the hop that makes it
a genuinely distributed trace — an external orchestrator originating the
request — does not.

This is the third and last change in milestone M5, and the one the milestone
exists for: it is the artifact for an n8n Core Platform application, where the
subject matter is the execution engine — worker pools, trigger reliability,
queue mode in self-hosted installations.

## What Changes

- Add self-hosted **n8n in queue-mode shape**: `n8n` (main), `redis` and
  `n8n-worker`, sharing the existing PostgreSQL through a dedicated `n8n`
  database created by a one-shot `n8n-db-init` service. `EXECUTIONS_MODE`
  defaults to `regular`; `redis` and `n8n-worker` sit behind
  `profiles: [queue]`, so queue mode is one variable rather than a rewrite.
- Enable n8n's **native OpenTelemetry tracing and Prometheus metrics on every
  process**, and add an n8n scrape job to the Collector, which wires up the
  orchestration dashboard that has been waiting since change 1.
- Add **two workflows on two different trigger types**, exported to
  `n8n/workflows/`:
  - `telemetry-ingest.json` — Schedule Trigger every 15 minutes.
  - `daily-inference-and-digest.json` — Schedule Trigger daily at 06:00
    Europe/Madrid, **plus a Manual Trigger**, so a demo never waits a day.
- Send the **`X-Ingest-Token`** header from both workflows. `harden-telemetry-ingest`
  made the endpoints check a token; this is the change that makes the producer
  send one, and it is the reason that change went first.
- Add `X-N8N-Execution-Id` / `X-N8N-Workflow-Id` attribute-stamping middleware
  on the backend, so a failed execution can be jumped to from a trace even if
  header injection is ever off.
- Add `scripts/export-n8n-workflow.sh`, which strips `id`, `versionId`,
  `meta.instanceId` and every `credentials` block before the JSON is committed.

### Two schedules, deliberately, and this is a correctness constraint

Ingest cadence and scoring cadence are separate concerns. A single workflow
doing both would re-score 96 times a day. `risk-inference` already survives that
— its trend window shifts on date change rather than per run — but the resulting
`trend` would be 6 points each holding the last run of its day rather than a
day's scoring, and the demo's headline artefact would quietly stop meaning what
the dashboard says it means. Two workflows on two trigger types is also the
better artifact: trigger reliability across schedule types is what the role
description names.

### The LLM invents the scenario; a Code node generates the numbers

The ingest workflow uses a Bedrock AI Agent node, which is the "AI orchestration"
half of the story, but it is constrained to emitting **one small typed scenario
object** through a Structured Output Parser. A Code node then synthesises the
readings deterministically from it.

Letting the model emit raw float vectors would be slow, unreproducible, and
would reintroduce the Kelvin/Celsius corruption through the front door: a model
asked for "a machine temperature" will emit `300` on some runs and `27` on
others, and both are accepted by the ingest schema's plausible-Celsius range
only by luck. The scenario object keeps the AI story and keeps the pipeline
testable.

## Capabilities

### New Capabilities

- `workflow-orchestration`: the system runs its ingest and re-scoring on
  schedules owned by a self-hosted orchestrator; the two run on separate
  cadences; a scheduled execution is one distributed trace from the orchestrator
  through the API to the database; a retried node cannot corrupt the data; the
  orchestrator authenticates to the write endpoints; its queue is observable;
  and the exported workflow definitions carry no credentials or instance
  internals.

### Modified Capabilities

- `observability`: the Collector gains an n8n Prometheus scrape target, and the
  cloud pipeline gains a filter dropping n8n's per-node `node.execute` spans.
  The existing "Incoming trace context is continued" requirement is **not**
  modified — it already covers the backend side of the linkage, and this change
  is what finally exercises it with a real external orchestrator.

## Impact

- **New files**: `n8n/workflows/telemetry-ingest.json`,
  `n8n/workflows/daily-inference-and-digest.json`,
  `n8n/workflows/README.md`, `scripts/export-n8n-workflow.sh`,
  `backend/app/core/orchestration_context.py` (the attribute-stamping
  middleware) and its tests, `docs/orchestration.md`.
- **Modified files**: `docker-compose.yml`, `observability/otel-collector-config.yaml`,
  `observability/otel-collector-grafana-cloud.yaml`, `observability/.env.example`,
  `observability/grafana/dashboards/orchestration.json` (replace the "Not wired
  up yet" panel), `backend/app/main.py`, `docs/deployment.md`,
  `docs/backend-standards.md`, `.gitignore`.
- **Not modified**: `docker-compose.prod.yml`. n8n is local-only — see below.
- **Frontend**: none. Grafana is a separate audience on its own port and is
  deliberately not embedded in the React app. The mandatory Playwright step is
  N/A.
- **Database**: no schema change to `elevator_db`. A second database `n8n` on
  the same PostgreSQL instance, owned entirely by n8n's own migrations.
- **Runtime cost**: `n8n` (768m) plus, under the `queue` profile, `redis`
  (~64m) and `n8n-worker` (640m). Measured headroom on the dev machine is
  4.3 GB available, and `poc-secretos` is already stopped.

## What this does not claim

The orchestration tier runs **locally**. Inference fires on a schedule *while
the stack is up*; it is not autonomous, and every artifact this change produces
must say so plainly. Overclaiming a "daily autonomous pipeline" is the single
thing that would undo the credibility the rest of the milestone buys.

The honest framing is also the more defensible architecture. What this builds is
the **edge-collection shape**: readings produced close to the asset and pushed to
a central service, with the orchestrator owning the trigger. In a real fleet the
ingest half runs at the edge, one instance per site; only scoring is central.
Collapsing both onto one machine is a simulation artefact, not a design
position. Moving the orchestration tier to the cloud so the trigger survives the
laptop being off is stated as future work — recorded here as a decision so it
does not read as an oversight.
