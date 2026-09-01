# Tasks: n8n-workflow-orchestration

## 0. Setup: Create Feature Branch (MANDATORY)

- [x] 0.1 Create branch `feature/n8n-workflow-orchestration`
- [x] 0.2 Verify current branch with `git branch --show-current`
- [x] 0.3 ~~Stacked on `feature/harden-telemetry-ingest` (PR #33)~~ — **PR #33 is
      merged** (squash, `d4dee9a`, 2026-08-31) and this branch is rebased onto
      `main`. No longer stacked; the `X-Ingest-Token` these workflows send is in
      `main`. Its open question is closed too: `telemetry_readings` was confirmed
      empty in production, so the migration's unbounded DELETE was a no-op there
- [x] 0.4 Verify change 2's endpoints still respond: `POST /api/telemetry/readings`
      and `POST /api/inference/run` with a token, `GET /api/elevators`

## 1. Environment and credentials

- [x] 1.1 Add the n8n variables to `observability/.env.example`:
      `N8N_ENCRYPTION_KEY`, `N8N_EXECUTIONS_MODE`, `TELEMETRY_INGEST_TOKEN`
- [x] 1.2 Generate a real `N8N_ENCRYPTION_KEY` into the git-ignored root `.env`
- [x] 1.3 Confirm `.gitignore` covers it and that no key is ever committed

## 2. Compose: n8n in queue-mode shape

- [x] 2.1 Add `n8n-db-init`: one-shot, `psql ... || CREATE DATABASE n8n`, gated
      with `service_completed_successfully`, mirroring the `migrate` service.
      **Not** `docker-entrypoint-initdb.d` — it only runs on an empty data
      directory and `postgres_data` already has data everywhere
- [x] 2.2 Add `n8n` (main), pinned to an explicit tag **≥ 2.19.0** — OTel tracing
      landed there and an older `:latest` has none, silently. `mem_limit: 768m`
- [x] 2.3 Add `redis` and `n8n-worker` behind `profiles: [queue]`;
      `EXECUTIONS_MODE` from an env var defaulting to `regular`.
      `n8n-worker` `mem_limit: 640m`
- [x] 2.4 Set `DB_POSTGRESDB_POOL_SIZE=4` on every n8n process
- [x] 2.5 Set `N8N_ENCRYPTION_KEY` **identically** on main and worker — a
      mismatch fails every credential-using node with an opaque error
- [x] 2.6 Confirm `docker-compose.prod.yml` is untouched
- [x] 2.7 Bring the stack up; verify n8n reaches Postgres and (under the profile)
      Redis, and that the editor loads

## 3. OpenTelemetry on every n8n process

- [x] 3.1 Add the OTel env block to `n8n` **and** `n8n-worker`, identical — plus
      **`N8N_ENABLED_MODULES: otel`** and **`N8N_OTEL_ENABLED: "true"`**, neither
      of which was in the plan. OTel ships as a module whose enabled list is
      empty by default, so the config var alone loads nothing, silently. And the
      service-name var is `N8N_OTEL_EXPORTER_SERVICE_NAME`, not
      `N8N_OTEL_SERVICE_NAME`. In
      queue mode the worker continues the trace; configured on main alone it
      executes everything and emits nothing
- [x] 3.2 Set `N8N_OTEL_TRACES_PRODUCTION_ONLY=false` in dev. **It defaults to
      `true`**, so editor "Test workflow" runs export zero spans — the single
      most likely way to conclude this is broken when it works
- [x] 3.3 Set `N8N_AGENTS_TRACING_RECORD_INPUTS=false` and
      `N8N_AGENTS_TRACING_RECORD_OUTPUTS=false`; both default to `true` and
      would ship prompts and model output outward
- [x] 3.4 Use the **base** OTLP URL, never a full path, and never alongside an
      explicit exporter endpoint. Wrong form 404s at DEBUG only
- [x] 3.5 Do not override `OTEL_PROPAGATORS` — W3C is the default and is what
      links the trace

## 4. Verify trace linkage (do this before building anything on it)

- [x] 4.1 Build a throwaway workflow with one HTTP node hitting `GET /api/elevators`
- [x] 4.2 **Activate** it — do not use the Test button
- [x] 4.3 In Tempo, confirm one trace spanning `n8n → elevator-backend → postgresql`
- [x] 4.4 It *was* unlinked, three times. Root causes, in order found:
      the `otel` module not enabled, then `N8N_OTEL_ENABLED` unset, then the
      wrong service-name variable. Resolved by reading the running image's
      `otel.constants.js` / `otel.config.js` rather than guessing
- [x] 4.5 Under the queue profile, confirm `n8n-worker` appears as its own
      service in Tempo
- [x] 4.6 Screenshot the **trace waterfall**, not the service graph. n8n emits no
      CLIENT-kind spans (`{resource.service.name="n8n-worker" && kind=client}`
      returns nothing), and Tempo builds service-graph edges from CLIENT→SERVER
      pairs — so `n8n → elevator-backend` can never appear there, and the
      backend's server span is attributed to the pseudo-node `user` instead. The
      trace view shows the hop the milestone is about; the service graph does
      not. Save to `docs/images/`

## 5. Backend: orchestration attribute middleware (TDD)

- [x] 5.1 Write a **failing** test: a request carrying `X-N8N-Execution-Id` and
      `X-N8N-Workflow-Id` produces a server span carrying both as attributes
- [x] 5.2 Write a **failing** test: a request with neither header is served
      normally and the span carries no orchestration attributes — not empty ones
- [x] 5.3 Implement `app/core/orchestration_context.py` and wire it in `main.py`
- [x] 5.4 Tests pass; **mutation-check**: remove the middleware → red
- [x] 5.5 Confirm it is a no-op with `otel_enabled` false

## 6. Collector: scrape n8n, and keep the cloud pipeline affordable

- [x] 6.1 Add an n8n scrape job to `observability/otel-collector-config.yaml`
      with an `n8n_role` label distinguishing main from worker
- [x] 6.2 Enable `N8N_METRICS` and `N8N_METRICS_INCLUDE_QUEUE_METRICS`;
      **workflow-id and node-type labels off** — cardinality
- [x] 6.3 `--force-recreate` the collector: it only reads its mounted config at
      startup
- [x] 6.4 **Verify the worker target actually scrapes** — it does, 131 series on
      2.37.6, so the plan's 404 caution does not apply. It found something worse:
      **two of the dashboard's three metric names do not exist in this version**
      and would have shown "No data" for ever. See
      `reports/2026-08-31-step-6-metrics-verification.md`
- [x] 6.5 Add a `filter` processor to the **cloud** pipeline only, dropping n8n
      `node.execute` spans; keep them locally where they are useful

## 7. Workflow: telemetry ingest (every 15 minutes)

- [x] 7.1 `Schedule Trigger → AI Agent (Bedrock Nova Lite, Structured Output
      Parser) → GET /api/elevators → Code → POST /api/telemetry/readings`.
      The agent runs **first**, on the trigger's single item: placed after the
      fleet fetch it would run once per lift, 100 model calls a tick
- [x] 7.2 Constrain the agent to **one typed scenario object** — no per-elevator
      numbers. Letting it emit readings reintroduces the Kelvin/Celsius
      corruption through the front door
- [x] 7.3 The Code node derives readings deterministically from the scenario,
      in Celsius/rpm/Nm/hours
- [x] 7.4 **Stamp `recorded_at` in the Code node, not the HTTP node.** This is
      what makes a retry idempotent: n8n re-runs the failed node with the same
      input, so an upstream timestamp survives the retry
- [x] 7.5 Attach the `X-Ingest-Token` as an n8n **credential**, never inline
- [x] 7.6 Verify a run: 201, rows land, each carrying a `trace_id`

## 8. Workflow: daily inference and ops digest

- [x] 8.1 `Schedule Trigger (06:00 Europe/Madrid) + Manual Trigger →
      POST /api/inference/run → GET /api/elevators → Code (digest facts) →
      AI Agent (ops digest)`
- [x] 8.2 Manual trigger present, so a demo never waits a day
- [x] 8.3 Same credential on the inference node
- [x] 8.4 Verify: scores move, and the trend still holds **exactly six** points

## 9. Prove the retry guarantee end to end

This is what `harden-telemetry-ingest` was carved out for; verify it here rather
than assuming it.

- [x] 9.1 Run the ingest workflow; record the row count and the fleet scores
- [x] 9.2 Force the HTTP node to fail and let n8n retry it — confirm the retry
      answers 201 with `accepted` 0 and the row count is unchanged
- [x] 9.3 Re-score; confirm the scores equal those from a single ingest
- [x] 9.4 Record the result in `reports/YYYY-MM-DD-step-9-retry-guarantee.md`

## 10. Export and publish the definitions

- [x] 10.1 Write `scripts/export-n8n-workflow.sh` stripping `id`, `versionId`,
      `meta.instanceId` and every `credentials` block via `jq`
- [x] 10.2 Export both workflows to `n8n/workflows/`
- [x] 10.3 **Verify a scrubbed definition still imports** into a clean instance
- [x] 10.4 Commit a canvas screenshot per workflow — both captured, renamed to
      match their JSON, and embedded in n8n/workflows/README.md
- [x] 10.5 `n8n/workflows/README.md`: what each does, its cadence, what it needs
      configured

## 11. Wire up the orchestration dashboard

- [x] 11.1 Delete the "Not wired up yet" text panel in
      `observability/grafana/dashboards/orchestration.json`
- [x] 11.2 ~~Confirm its three existing queries now return data~~ — they could
      not: two named metrics that do not exist. Rewritten against the real names
      and each of the five queries verified against Prometheus
- [x] 11.3 Add a panel only for what step 6.4 proved actually scrapes

## 12. Review and Update Existing Tests (MANDATORY)

- [x] 12.1 Review `tests/unit/test_telemetry_spans.py` for the new middleware
- [x] 12.2 Review the compose-file assertions in `tests/unit/test_dev_compose.py`
      — add one that `docker-compose.prod.yml` defines no orchestrator service
- [x] 12.3 Update every test this change invalidates, and no others

## 13. Unit Tests and DB State Verification (MANDATORY)

- [x] 13.1 Capture the pre-test DB baseline
- [x] 13.2 Run targeted tests, then the full suite with coverage
- [x] 13.3 `ruff check` (the project does not use `ruff format`)
- [x] 13.4 Verify post-test DB state matches the baseline
- [x] 13.5 Create `reports/YYYY-MM-DD-step-13-unit-tests.md`

## 14. Manual Endpoint Testing (MANDATORY — AGENT MUST EXECUTE)

- [x] 14.1 `docker compose build backend migrate` — building `backend` alone
      leaves `migrate` on its old image and it applies nothing, silently
- [x] 14.2 Exercise both write endpoints with and without the token
- [x] 14.3 Restore DB state afterwards (`docker exec **-i**` for a heredoc —
      without `-i` psql gets no stdin and reports success having done nothing)
- [x] 14.4 Create `reports/YYYY-MM-DD-step-14-endpoint-testing.md`

## 15. E2E Testing with Playwright MCP (MANDATORY if frontend changed)

- [x] 15.1 **N/A** — nothing in `frontend/` is touched and no response shape
      changes. Grafana is a separate audience on its own port. Record the
      determination in the step 14 report

## 16. Update Technical Documentation (MANDATORY)

- [x] 16.1 New `docs/orchestration.md`: the two workflows, their cadences, the
      queue-mode switch, the trace-linkage traps, **and plainly that schedules
      fire only while the local stack is up**
- [x] 16.2 `docs/deployment.md`: state that n8n is local-only and production
      carries no orchestrator
- [x] 16.3 `docs/backend-standards.md`: the orchestration-attribute middleware
- [x] 16.4 Run `/update-docs` and act on anything 16.1–16.3 missed

## 17. Milestone acceptance (M5 end to end)

- [x] 17.1 Stack up, all services healthy
- [x] 17.2 An activated workflow produces one trace `n8n → backend → postgresql`
      with `n8n.execution.id` on the server span
- [x] 17.3 Fleet-health dashboard **FAILS** — 4 of 6 instruments emit nothing,
      a change-1 defect registered as a High backlog task, diagnosed in the
      step 17 report and out of scope here
- [x] 17.4 Grafana Cloud shows the same traces and
      `otelcol_exporter_send_failed_spans` for the cloud exporter is 0
- [x] 17.5 **Fleet score variance > 0** — the Kelvin canary
- [x] 17.6 Record it all in `reports/YYYY-MM-DD-step-17-milestone-acceptance.md`

## 18. Independent Review and Close-out

- [x] 18.1 Mutation-check every guard added by this change and record the results
- [x] 18.2 Run `/adversarial-review` **as an independent cold-start agent**, not
      as a self-review — on the previous change the self-review found 3 issues
      and an independent session found 7 more, two of them in things the
      self-review had touched and got wrong
- [x] 18.3 Fix every finding, then re-run 18.1 — 6 Major and 10 Minor addressed;
      all five reviewer-identified mutation survivors now go red
- [ ] 18.4 `/archive` and sync `openspec/specs/workflow-orchestration/`
- [ ] 18.5 `/commit` and open the PR (merge needs approval)
- [ ] 18.6 Set the Notion task *n8n workflow orchestration (self-hosted, queue
      mode)* to Done **on merge**, and close out the M5 milestone
