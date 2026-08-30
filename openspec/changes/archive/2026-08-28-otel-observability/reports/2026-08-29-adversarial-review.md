# Adversarial Review — otel-observability

- **Date**: 2026-08-29
- **Change**: 2026-08-28-otel-observability
- **Sources**: `proposal.md`, `design.md`, `specs/observability/spec.md`, `tasks.md`,
  `git diff main..HEAD` (32 files, +3752/-43), and the running Docker stack.

## Reviewer independence — stated limitation

The skill asks for a different agent or session than the one that implemented the
change. This review was run by the **implementing agent**, so it carries author
bias. It is compensated for by refusing to accept any claim on inspection alone:
every finding below was produced by executing something against the running
stack, and two of them contradict what the author believed was working. A second
reviewer is still advisable before merge.

## Spec and task alignment

All 80 tasks complete. Every requirement in `specs/observability/spec.md` maps to
implementation and to at least one test or a recorded manual verification.

One spec amendment was made mid-change and committed separately (`3dd7189`)
before the code: model token usage stays on the botocore span rather than being
duplicated onto the domain span.

## Findings

| Severity | Area | Finding | Evidence | Fix |
|---|---|---|---|---|
| **Major** | Logs pipeline | The proposal and design both claim logs are emitted over OTLP. Nothing was emitting them. `LoggingInstrumentor` only injects trace ids into the log *format*; without an explicit `LoggerProvider` and handler the Collector's logs pipeline received nothing, and nothing reported an error. | `otelcol_receiver_accepted_log_records` had no series at all; Loki had zero streams for `elevator-backend`; no `LoggerProvider` anywhere in `app/`. | **Fixed in code + tests.** Added `LoggerProvider`, `BatchLogRecordProcessor` and the non-deprecated handler from `opentelemetry-instrumentation-logging`. Verified: 36 log records received and exported, and the Bedrock fallback warning is queryable in Loki with `severity_text=WARN`. Two regression tests added. |
| **Minor** | Test coverage | The spec scenario *"Collector unreachable while telemetry is enabled"* had no automated test. | No test referenced connection failure. | Behaviour **verified manually**: with the Collector stopped, the backend starts healthy, serves `200` on all endpoints at 20 ms, and logs the export failure rather than raising. Left as a follow-up test rather than a blocker, because the SDK owns this behaviour and the manual check is recorded here. |
| **Minor** | Pre-existing data semantics | The fleet-health metric counts 30 out-of-scope elevators separately, while `GET /api/elevators` reports the same units as `risk_level: "low"`, derived from their placeholder `risk_score` of 0.0. `docs/data-model.md` says out-of-scope units represent *genuine absence, not zero risk*. | Metric: high 5 / medium 5 / low 60 / out_of_scope 30. API: high 5 / medium 5 / low 90. | **Not this change.** Pre-existing API behaviour; correcting it would alter a response contract that is out of scope here. Recommend a Notion backlog task. Surfacing it is exactly what the observability work is for. |
| **Question** | Dashboards | `orchestration.json` queries n8n metric names (`n8n_queue_jobs_waiting`, `n8n_workflow_executions_total`) that cannot be verified until n8n runs. | No n8n instance yet. | Accepted: the panel is explicitly labelled as not wired up, and the n8n change will confirm the names. |

### Adversarial checks that found nothing

Recorded so the absence is evidence rather than an untested assumption.

- **Secrets**: no `glc_` token or credential string in any commit on the branch; `.env` never tracked; `git check-ignore` confirms coverage by the `*.env` rule.
- **Scope**: `docker-compose.prod.yml` unchanged (0 files); `frontend/` unchanged (0 files). Production exposes no Collector, no Grafana, no new port.
- **Prompt leakage**: every span attribute in a briefing trace searched for exact markers of the system prompt, the prompt scaffold, a seeded visit-note value and the returned briefing text — clean. An earlier looser heuristic produced a false positive on `db.statement`, which matched only a column name.
- **Log leakage to the cloud**: `otelcol_exporter_sent_log_records` exists only for `otlp_http/local`. Logs deliberately never leave the machine, so the `exc_info=True` traceback on a Bedrock failure stays local.
- **Silent-failure guards have teeth**: the concurrency test was verified to fail (0.60 s vs 0.53 s) when the `anyio.to_thread` offload is reverted. The database-span test exists specifically because the unbound SQLAlchemy call fails silently.
- **Cardinality**: `elevator_fleet_count` has exactly 4 series; HTTP metrics group by `http_route`, producing 2 series across 100 elevators.

## Verdict

**PASS WITH GAPS**

The one Major finding was fixed and verified within this review. The remaining
items are a follow-up test and a pre-existing data-semantics issue that belongs
in the backlog, not in this change.

## Recommended next steps before archive

1. Register the out-of-scope-risk-level issue as a Notion backlog task.
2. Optionally add an automated test for the unreachable-Collector scenario.
3. Have a second agent or session re-review, given the stated author bias.
