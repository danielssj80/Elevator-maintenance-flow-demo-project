# Step 6 Report — Collector Scrape and Metric Verification

- **Date**: 2026-08-31
- **Change**: n8n-workflow-orchestration
- **n8n version**: 2.37.6

Task 6.4 says: *verify the worker target actually scrapes before building any
panel on it*. It found more than it was looking for.

## What the dashboard from change 1 was asking for, and what exists

`observability/grafana/dashboards/orchestration.json` shipped in change 1 with a
"Not wired up yet" placeholder and three queries written from documentation.
Two of the three metric names do not exist in 2.37.6, and would have rendered
"No data" for ever — which reads as a broken scrape rather than a wrong query.

| Dashboard asked for | Exists? | Real name |
|---|---|---|
| `n8n_queue_jobs_waiting` | no | `n8n_scaling_mode_queue_jobs_waiting` |
| `n8n_queue_jobs_active` | no | `n8n_scaling_mode_queue_jobs_active` |
| `n8n_workflow_executions_total` | no | `n8n_workflow_execution_duration_seconds_count` (a histogram) |

The `status` label change 1 grouped by **does** exist
(`status="success"`, `mode="trigger"`), so that half was right and only the
metric name was wrong. An intermediate fix here replaced it with `n8n_role`
before the label was verified; that was reverted once real data proved `status`
is there. Also available and now on the dashboard:
`n8n_scaling_mode_queue_jobs_completed` / `_failed`, `n8n_active_workflow_count`,
`n8n_instance_role_leader`, and the agent series
`n8n_instance_ai_tokens_total{type}` / `n8n_instance_ai_cost_usd_total` — counts
only, no prompt content.

Names read from `dist/metrics/prometheus/queue-metrics.service.js` in the running
image, not from documentation.

## Queue metrics: the spec was right

`queue-metrics.service.js` gates them on
`includeQueueMetrics && mode === 'queue' && instanceType === 'main'`, which is
exactly what the spec requirement says. Confirmed by running the profile:

```
$ docker compose exec -T n8n printenv EXECUTIONS_MODE
queue
$ curl -s localhost:5678/metrics | grep '^n8n_scaling_mode_queue'
n8n_scaling_mode_queue_jobs_waiting 0
n8n_scaling_mode_queue_jobs_active 0
n8n_scaling_mode_queue_jobs_completed 0
n8n_scaling_mode_queue_jobs_failed 0
```

## The worker serves /metrics — the plan's warning does not apply here

The plan carried a caution that n8n workers have a history of 404ing on
`/metrics`, and told us to verify before building a panel. On 2.37.6 the worker
answers with **131** `n8n_*` series. Queue metrics are correctly absent from it,
by the gate above, not by a fault.

```
role=main    instance=n8n:5678        up=1
role=worker  instance=n8n-worker:5678 up=1
```

## A trade-off, recorded rather than hidden

With the `queue` profile **off**, `n8n-worker` does not resolve and the Collector
logs `Failed to scrape Prometheus endpoint ... server misbehaving` every 15
seconds. The `up{n8n_role="worker"} == 0` series that results is truthful and
useful, but the log noise has a cost: change 1's design leans on Collector
self-telemetry to catch a silently failing Grafana Cloud exporter, and a warning
every 15 seconds is how people learn to stop reading that log.

Kept as-is for now because the milestone's end state runs queue mode, where both
targets resolve and the log is clean (verified: 0 warnings in the last minute
with the profile up). If the profile is going to be off routinely, the worker
target should move to a queue-profile-only Collector config.

## A measurement artefact worth not repeating

`GET /api/search/tag/service.name/values` on Tempo reported only
`elevator-backend` and `elevator-inference` after the queue-mode restart, which
looked like the worker configuration having broken tracing. It had not. A
range-scoped search found the trace immediately:

```
$ curl --get http://localhost:3200/api/search \
    --data-urlencode 'q={resource.service.name="n8n-main"}' \
    --data-urlencode "start=$((NOW-900))" --data-urlencode "end=$NOW"
n8n-main: 1 traces — 34fd686e4721e3d1e5a8d19859125d75  workflow.execute
```

The tag-values endpoint is time-windowed. Use a range-scoped search before
concluding a service has stopped reporting.

## Verification of every dashboard query

Against Prometheus, after an activated execution in queue mode:

| Query | Series |
|---|---|
| `n8n_scaling_mode_queue_jobs_waiting` | 1 |
| `n8n_scaling_mode_queue_jobs_active` | 1 |
| `n8n_workflow_execution_duration_seconds_count` | 1 (`status="success"`, `mode="trigger"`, `n8n_role="main"`) |
| `up{job="n8n"}` | 2 |
| `n8n_instance_ai_tokens_total` | 4 |

## Outcome

**PASS** — tasks 6.1–6.4 and 11.1–11.3 complete. 6.5 (the cloud-pipeline
`filter` processor for `node.execute` spans) is still open.
