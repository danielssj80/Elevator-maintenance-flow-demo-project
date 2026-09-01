# Orchestration

n8n owns the schedules this system used to lack. Two workflows on two trigger
types: telemetry ingest every 15 minutes, and a daily re-scoring that also
carries a manual trigger.

## What this is not

**It runs locally, and only while the local stack is up.** There is no
orchestrator in production — `docker-compose.prod.yml` defines none, and a test
asserts that. Close the laptop and nothing fires.

That is worth stating first, because "a predictive maintenance pipeline that
re-scores the fleet daily" is easy to read as a service that runs by itself.
It is not one. What it is, is the **edge-collection shape**: readings produced
close to the asset and pushed to a central service, with the orchestrator owning
the trigger. In a real fleet the ingest half would run at the edge — one instance
per site or region — and only scoring would be central. Collapsing both onto one
machine is a simulation artefact, not a design position.

Moving the orchestration tier to the cloud, so the trigger survives the machine
being off, is the honest next step and is deliberately not attempted here.

Production is also unreachable from these workflows by two independent means:
they address the backend as `http://backend:8000` on the compose network, which
does not resolve outside it; and the telemetry and inference routers are not
registered when `deployment_environment` is production, so those paths return
404 there.

## The stack

| Service | Role |
|---|---|
| `n8n` | Main process, editor on :5678, owns the schedules |
| `n8n-db-init` | One-shot; creates the `n8n` database on the existing PostgreSQL |
| `redis` | Queue backend — `queue` profile only |
| `n8n-worker` | Executes workflows in queue mode — `queue` profile only |

```bash
docker compose up -d                                        # regular mode
N8N_EXECUTIONS_MODE=queue docker compose --profile queue up -d   # queue mode
```

Queue mode is one variable and a profile flag, not a rewrite. That was the point
of writing the compose in queue-mode shape from the start.

**The `n8n` database is created by a one-shot service, not by
`docker-entrypoint-initdb.d`.** That recipe runs only when the data directory is
empty, and `postgres_data` already has data on any machine that has run this
project before — so it silently never runs and n8n fails at startup with
"database n8n does not exist".

## Configuration that is easy to get wrong

Every item here fails **silently**. Each was found by running the stack, not by
reading documentation, and each is quoted from the running image rather than
remembered.

| Setting | Why it matters |
|---|---|
| `N8N_ENABLED_MODULES: otel` | OTel ships as an n8n *module* and the enabled list defaults to empty. Without this, `N8N_OTEL_ENABLED` configures a module that was never loaded. Nothing is logged. |
| `N8N_OTEL_ENABLED: "true"` | Defaults to `false`. |
| `N8N_OTEL_EXPORTER_SERVICE_NAME` | **Not** `N8N_OTEL_SERVICE_NAME`, which n8n does not read — the wrong spelling is ignored and the service appears in Tempo as the default `n8n`. |
| `N8N_OTEL_TRACES_PRODUCTION_ONLY: "false"` | Defaults to `true`. The editor's "Test workflow" button is a *manual* execution and exports zero spans, so iterating in the editor looks exactly like tracing being broken. **Verify linkage with an activated workflow.** |
| `N8N_ENCRYPTION_KEY` | Must be identical on main and every worker, or workers cannot decrypt credentials and every node using one fails with an error that never mentions encryption. |
| The whole OTel block | Must be identical on main and every worker. In queue mode the worker runs the executions; configured on main alone it emits nothing, and the result is a parent span with no children — which reads as "the workflow never ran". |
| `N8N_AGENTS_TRACING_RECORD_INPUTS/OUTPUTS` | Both default to `true` and would ship prompts and model output to Grafana Cloud. |

`tests/unit/test_dev_compose.py` asserts the encryption key and the OTel block
match across main and worker, because "they read the same variable" stops being
true the moment someone gives one of them its own value.

## Metrics

Scraped by the Collector from both processes, labelled `n8n_role`. The names in
2.37.6 are not the ones the documentation-era dashboard assumed:

| Metric | Notes |
|---|---|
| `n8n_workflow_execution_duration_seconds_count` | Executions. Carries `status` and `mode` labels. |
| `n8n_scaling_mode_queue_jobs_waiting` / `_active` / `_completed` / `_failed` | Queue depth. **Main only, and only in queue mode** — gated in `queue-metrics.service.js` on `includeQueueMetrics && mode === 'queue' && instanceType === 'main'`. |
| `n8n_active_workflow_count`, `n8n_instance_role_leader` | Fleet-level state. |

Workflow-id and node-type labels are **off**. One careless label on a 100-lift
fleet is what a 10k-series free tier is lost to.

`n8n_instance_ai_*` looks like agent telemetry and is not — it belongs to n8n's
own "instance AI" feature and stays at zero through a successful AI Agent run.
A dashboard panel was built on it and removed.

With the `queue` profile down, the worker target does not resolve and the
Collector logs a scrape warning every 15 seconds. The resulting
`up{n8n_role="worker"} == 0` is truthful, but the log noise has a cost: the
Collector's own log is where a silently failing Grafana Cloud exporter shows up.
If the profile is going to be down routinely, move the worker target to a
queue-profile-only Collector config.

## Traces

n8n injects W3C `traceparent` into outbound HTTP, and the backend continues it,
so a scheduled execution is one trace from the orchestrator through the API to
the database. This needs no code — just don't override `OTEL_PROPAGATORS`.

`app/core/orchestration_context.py` additionally stamps `X-N8N-Execution-Id` and
`X-N8N-Workflow-Id` onto the server span, so a failed execution can be reached
from a trace even if header injection is off.

On the Grafana Cloud pipeline only, a `filter` processor drops n8n's per-node
`node.execute` spans: n8n emits one per node execution, and at a 15-minute
schedule they are most of the volume. They stay in the local backend, where they
are what makes a slow or failing node visible.

## The workflows

See [`n8n/workflows/README.md`](../n8n/workflows/README.md) for what each does
and how to import one. Two properties are load-bearing and easy to break:

- **`recorded_at` is stamped in the Code node, not the HTTP node.** n8n retries a
  failed node by re-running *that* node with the same input, so a timestamp
  computed upstream survives the retry and the backend recognises the batch as
  the same readings. Computed downstream, every retry would be a new batch and
  would weigh twice in the window average the risk score is built from.
- **The agent invents a scenario; a Code node generates the numbers.** A model
  asked for "a machine temperature" answers 300 on some runs and 27 on others,
  and both survive the ingest endpoint's validation.

## Generated telemetry and what it is worth

The generator mirrors `_synthesise_features` in
`backend/ml/generate_predictions.py` — the function that produced the committed
`predictions.json` — so online and offline scoring see the same feature space.
The scenario the agent invents is constrained to that space: ambient temperature
23–31 °C, because the model was trained on `gauss(300 K, 2)` and anything
outside that band is extrapolation rather than prediction.

**Known limitation, and worth understanding before reading anything into a
demo.** At this operating point the model's risk is not driven by a lift's age or
usage. Speed sits at the 1168 rpm floor for any lift with torque above ~23 Nm, so
AI4I's heat-dissipation rule (rise < 8.6 K with speed < 1380 rpm) gates almost the
whole fleet, and which lifts are flagged follows the torque and temperature draw.
`predictions.json` has the same property: ELV-001 scores 0.7999 there because its
torque draw was 9.5 Nm, not because it is 25 years old.

Conditioning the generated dispersion on consumed motor life was tried, to make
risk follow condition. It moved the variance and did not change which lifts were
flagged, and it was reverted. Making risk track machine condition is a modelling
question, not a generator one, and inventing the correlation in synthetic data
would dress up the demonstration rather than drive it.
