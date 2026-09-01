# Step 18.1 Report — Mutation Checks

- **Date**: 2026-09-01
- **Change**: n8n-workflow-orchestration

Every guard this change adds, broken deliberately, suite re-run, restored. Run
as each guard was written rather than as an audit pass at the end.

| # | Mutation | Result |
|---|---|---|
| A | Remove `OrchestrationContextMiddleware` from `main.py` | **red** — 3 tests |
| B | Record empty header values instead of skipping them | **red** — `test_an_empty_header_value_is_not_recorded` |
| C | Add an `n8n` service to `docker-compose.prod.yml` | **red** — `test_prod_compose_defines_no_orchestrator` |
| D | Remove `profiles: [queue]` from `n8n-worker` | **red** — `test_dev_compose_keeps_the_queue_tier_behind_a_profile` |
| E | Give the worker a different `N8N_OTEL_TRACES_PRODUCTION_ONLY` | **red** — `test_main_and_worker_share_one_encryption_key_and_otel_block` |

Suite green at **226 passed**, `ruff check` clean, coverage 96%.
`app/core/orchestration_context.py` is at 92%; the two uncovered lines are the
non-HTTP ASGI scope branch.

## What is not covered by a test, and why

Most of this change is configuration and workflow definitions, which the suite
cannot exercise. Those were verified by running the stack, and the evidence is
in the step 6, 7/9 and 17 reports rather than in an assertion:

- Trace linkage `n8n → backend → postgres`, verified by reading a real trace out
  of Tempo. There is no test; the closest is the backend's existing
  "incoming trace context is continued" scenario, which covers our half only.
- The retry guarantee end to end, verified by re-posting a real workflow payload.
  The backend half of it *is* tested, in `harden-telemetry-ingest`.
- The cloud span filter, verified by the Collector's own
  `otelcol_processor_filter_spans_filtered` counter.
- Every n8n environment variable. These are the highest-risk items in the change
  — three of them were silently wrong at first — and nothing but running the
  stack would have caught any of them.

The compose-file tests are the one place this gap is partly closed, and they are
deliberately about the properties that fail *silently* rather than about every
setting.

## Guards found dead by mutation

None in this change. Four were found in **change 1** by the milestone acceptance
step — see the step 17 report and the backlog task — but they are not this
change's code and were not touched here.
