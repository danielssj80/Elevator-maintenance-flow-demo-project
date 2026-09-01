# Step 17 Report — M5 Milestone Acceptance

- **Date**: 2026-09-01
- **Change**: n8n-workflow-orchestration

The acceptance list for the whole milestone, executed against the running stack.

## 17.1 — Stack healthy

`db`, `backend`, `inference`, `frontend`, `lgtm`, `otel-collector`, `n8n`,
`n8n-worker`, `redis` all up, with the `queue` profile active.

## 17.2 — One trace, orchestrator to database

A scheduled execution (`99a2ee47504c17087ddffbaf6ff42582`), read from Tempo:

```
n8n-main          workflow.execute
n8n-worker        workflow.execute, node.execute x4
elevator-backend  GET /api/elevators, POST /api/telemetry/readings, SELECT, INSERT
n8n.execution.id = 82   (on the backend server span)
```

Three services in one trace, and the orchestration attribute the middleware
stamps. This also settles task 4.5 properly: **the worker appears as its own
service**, which is the check that the OTel block really is identical on both
processes — configured on main alone, the worker executes everything and emits
nothing.

## 17.3 — Fleet-health dashboard — **FAIL, and the cause is in change 1**

`elevator_fleet_count` moves correctly (`high=2, medium=1, low=67,
out_of_scope=30`). The other two panels on that dashboard cannot ever move.

`app/core/metrics.py` registers six instruments; only two produce a series:

```
$ curl -s localhost:9090/api/v1/label/__name__/values | grep elevator_
['elevator_briefing_requests_total', 'elevator_fleet_count']
```

- `elevator.inference.last_run.age` and `elevator.telemetry.stale.count` are
  observable gauges whose callbacks return without yielding when the snapshot
  field is `None` — and `fleet_health_service.py:45-46` passes `None` for both,
  literally.
- `elevator.inference.runs` and `elevator.inference.duration` are created,
  assigned to module globals, and never recorded: there is no
  `record_inference_run()` and `inference_service.py` never imports them.

`fleet-health.json` queries two of them, so change 1 shipped a dashboard with two
panels that have been empty since they were written. Nobody noticed because the
`elevator_fleet_count` panels beside them work.

Out of scope to fix here — it is the `observability` capability, and folding a
change-1 defect into a change-3 review helps nobody. Registered as
[Four of six fleet-health instruments emit nothing](https://app.notion.com/p/3ce3ada00a958173a8fde0a8866aac63)
(Backlog, High). The real fix is the test nobody wrote: *assert that every
declared instrument produces at least one observation*. All four passed change 1
and its four adversarial rounds because nothing anywhere checks that.

## 17.4 — Grafana Cloud

With the cloud overlay up:

```
otelcol_exporter_sent_spans{exporter="otlp_http/grafana_cloud"} = 490
otelcol_exporter_queue_size{...grafana_cloud} = 0
no send_failed series at all; no 401 or auth errors in the log
```

Reverted to the local-only collector afterwards, so a 15-minute schedule does not
spend free-tier quota unattended.

## 6.5 — The cloud span filter, and a design error it exposed

The `filter` processor was added to drop n8n's per-node `node.execute` spans from
the cloud pipeline only. First attempt: **0 spans filtered**, and cloud and local
exported identical counts.

The span name was right — Tempo shows `node.execute` verbatim, 7 of them per
execution. The error was architectural: **a processor belongs to a pipeline, not
to an exporter.** Both exporters sat in one `traces` pipeline, so a filter there
would have dropped the spans from the local backend too — the one place they are
useful for debugging a workflow. Split into `traces/local` and `traces/cloud`,
both reading the same `otlp` receiver:

```
otelcol_processor_filter_spans_filtered{filter="filter/drop_n8n_node_spans"} = 7
sent to cloud 490, received 503  ->  490 + 7 filtered accounts for the input
```

`error_mode` was also changed from `ignore` to `propagate`. With `ignore`, an
OTTL condition that fails to evaluate is a broken filter that says nothing:
spans flow, the drop count stays at zero, and it looks exactly like there being
nothing to drop — which is precisely how the first version appeared to work.

## 17.5 — Fleet score variance > 0 (the Kelvin canary)

`variance = 0.033381` across 22 distinct scores. Passes.

The canary did real work in this change rather than rubber-stamping: it failed
four separate times, each a different defect in the generator, and each would
have shipped a demonstration of seventy identical healthy lifts. See the step 7/9
report.

## Outcome

**PASS with one FAIL carried to the backlog.** 17.1, 17.2, 17.4, 17.5 and 6.5
pass. 17.3 fails on a change-1 defect that is registered, diagnosed and out of
scope here.
