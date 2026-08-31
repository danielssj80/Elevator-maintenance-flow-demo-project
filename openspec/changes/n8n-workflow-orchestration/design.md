# Design: n8n-workflow-orchestration

## Layering

n8n sits *outside* the three-layer backend and talks to it only over HTTP, the
same way any external client would. Nothing in `app/` learns that n8n exists,
with one exception: a middleware that reads two request headers and records them
as span attributes. That is an observability concern in `core/`, not a coupling
— it degrades to nothing when the headers are absent, and the backend keeps
working with no orchestrator at all.

## Decision 1 — queue-mode *shape* from day one, queue mode behind a profile

`docker-compose.yml` gains `redis` and `n8n-worker` behind `profiles: [queue]`,
with `EXECUTIONS_MODE` read from an environment variable defaulting to
`regular`. Turning queue mode on is then one variable and a profile flag rather
than a compose rewrite.

Queue mode is the *narrative* for an n8n Core Platform application, so it is not
optional in the end. It is behind a profile at the start because it costs
~700 MB and an unbounded debugging tail, and it does not change what the
distributed-trace screenshot looks like. Twenty minutes of shape now turns
"add queue mode" from a rewrite into flipping a variable.

**`N8N_ENCRYPTION_KEY` must be identical on main and every worker.** If it is
not, workers cannot decrypt credentials and every node using one fails with an
opaque error that does not mention encryption.

**The OTel environment block must also be identical on every process.** In queue
mode a worker reads the parent trace context from the database and continues it;
if only main is configured, the worker executes everything and emits nothing, and
the result is a parent span with no children and no HTTP calls — which reads as
"the workflow never ran" rather than as a configuration gap.

## Decision 2 — reuse the existing PostgreSQL, with a one-shot init service

A second PostgreSQL container costs ~150 MB against a budget that is already
tight, and reuse keeps one backup and reset story. n8n gets its own `n8n`
database on the existing instance.

**Not** via `docker-entrypoint-initdb.d`. That recipe runs only when the data
directory is empty, and `postgres_data` already has data on every existing dev
machine — so it silently never runs and n8n fails at startup with "database n8n
does not exist". Instead a one-shot `n8n-db-init` service runs
`psql ... || CREATE DATABASE n8n`, gated with
`condition: service_completed_successfully`, mirroring the existing `migrate`
service. That pattern is already in the file and already understood.

`DB_POSTGRESDB_POOL_SIZE=4` per n8n process: main, worker, their TypeORM pools,
SQLAlchemy and the inference service can otherwise walk into PostgreSQL's default
`max_connections=100`.

## Decision 3 — trace linkage, and the trap that will waste an afternoon

n8n injects W3C `traceparent`/`tracestate` into outbound HTTP made by nodes, and
`N8N_OTEL_TRACES_INJECT_OUTBOUND` defaults to `true`. The backend already
continues an incoming `traceparent` — that requirement exists in the
`observability` spec and is tested. So linkage needs no code: just don't
override `OTEL_PROPAGATORS`.

Two conditions, both silent when unmet:

- **Pin the n8n image tag to ≥ 2.19.0.** OTel tracing landed there. An older
  `:latest` pull simply has no tracing, with nothing to indicate why.
- **`N8N_OTEL_TRACES_PRODUCTION_ONLY` defaults to `true`.** Traces export for
  *production* executions only. Clicking "Test workflow" in the editor — which is
  exactly how the workflow gets built — is a *manual* execution and exports zero
  spans. Set it to `false` in dev, and **verify linkage with an activated
  workflow, not the Test button.** This is the single most likely way to conclude
  the whole feature is broken when it is working.

The `X-N8N-Execution-Id` / `X-N8N-Workflow-Id` middleware goes in regardless
(~30 lines). It is the honest fallback if injection is ever off, and it is
independently useful: it makes a failed execution reachable from a trace.

**Do not fabricate a `traceparent` in a Code node.** The sandbox has no OTel API,
so a hand-built header would point at a span that never existed, and Tempo would
render a dangling parent — which looks broken rather than absent.

## Decision 4 — the agent invents a scenario; code generates the numbers

The ingest workflow is
`Schedule → GET /api/elevators → AI Agent (Bedrock Nova Lite) → Code → POST /api/telemetry/readings`.

The agent emits **one typed scenario object** through a Structured Output Parser
— something like a season, an ambient band, a load profile and an optional
degrading-unit hint. The Code node derives every reading from it
deterministically.

Rejected: letting the agent emit the readings. It is slow, unreproducible, and
it reintroduces the Kelvin/Celsius corruption through the front door. A model
asked for "a machine temperature" emits `300` on some runs and `27` on others.
Both survive the ingest schema — `27` is plainly in range, and `300` is rejected
by the plausible-Celsius bound only because that bound happens to exist. The
scenario object keeps the AI-orchestration story a job application wants while
leaving the numeric path testable.

**`recorded_at` is stamped in the Code node, not in the HTTP node.** This is
what makes idempotency work across a retry: n8n retries a failed node by
re-running *that node* with the same input, so a timestamp computed upstream is
carried unchanged into the retry and the batch is recognised as the same
readings. A timestamp computed inside the HTTP node, or by the server, would
make every retry a new batch and defeat `harden-telemetry-ingest` entirely.

## Decision 5 — what the workflows are allowed to know

The `X-Ingest-Token` is held as an n8n **credential**, referenced by the HTTP
nodes, never inline in the workflow JSON. The export script strips credential
blocks anyway, so an inline token would be both a leak and a definition that
breaks on export.

## Decision 6 — export hygiene is a script, not a habit

`scripts/export-n8n-workflow.sh` runs the export through `jq`, removing `id`,
`versionId`, `meta.instanceId` and every `credentials` block. Credential ids leak
instance internals and make the file un-importable elsewhere.

A canvas screenshot is committed alongside each definition. For the audience this
milestone exists for, the screenshot is what actually gets looked at.

## Decision 7 — metrics, and one thing to verify before building a panel

`N8N_METRICS` and `N8N_METRICS_INCLUDE_QUEUE_METRICS` on; **workflow-id and
node-type labels off**, because 100 elevators taught this project what a careless
label does to a 10k-series free tier.

Queue metrics come from Bull and are exposed on **main only**. Scrape both
targets with an `n8n_role` label, but expect queue depth from main — and
**verify the worker target actually scrapes before building a panel on it**.
n8n has a long history of `/metrics` 404ing on workers.

`observability/grafana/dashboards/orchestration.json` already exists from change
1 with a "Not wired up yet" text panel and three queries. This change deletes
that panel; it does not build a new dashboard.

## Decision 8 — the cloud pipeline drops per-node spans

n8n emits one `node.execute` span per node execution, by default. At a 15-minute
schedule that is a lot of spans for a free tier that also has to carry the
interesting ones. A `filter` processor on the **cloud** pipeline only drops
them; the local backend keeps them, which is where they are actually useful for
debugging a workflow.

`N8N_AGENTS_TRACING_RECORD_INPUTS` and `..._RECORD_OUTPUTS` both default to
**`true`** and are set to `false`. They would ship prompts and model output to an
external backend, which is the same mistake the briefing instrumentation
deliberately avoided in change 1.

## Out of scope

- **Deploying n8n to production.** `docker-compose.prod.yml` is untouched. The
  orchestrator is local-only and every artifact says so.
- **Making the pipeline autonomous.** Schedules fire while the stack is up.
  Moving the orchestration tier to the cloud is recorded as future work in
  `docs/orchestration.md`, not attempted here.
- **Multi-main / high-availability n8n.** Queue mode with a single worker is the
  scope; multi-main is a licensing and Redis-topology question that adds nothing
  to the artifact.
- **Any frontend change.** Grafana is a separate product for a separate
  audience, on its own port, deliberately not embedded in the React app.
