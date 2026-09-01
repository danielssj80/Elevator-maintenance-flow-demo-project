# Independent Adversarial Review

- **Date**: 2026-09-01
- **Change**: n8n-workflow-orchestration
- **Reviewer**: independent cold-start session, own git worktree, no access to the
  implementing session's reasoning
- **Verdict**: **FAIL** — 6 Major, 10 Minor, 1 Question. All addressed below.

The reviewer was told where the risk actually was: most of this change is not
Python. It is compose configuration, two Collector configs, two n8n workflow
definitions containing JavaScript, and three shell scripts — none of which the
test suite can reach. That is where five of the six Majors were.

## Majors

| # | Finding | Disposition |
|---|---|---|
| M1 | **The cloud overlay duplicated every span in the local backend.** Renaming the overlay's pipeline to `traces/local:` did not override the base config's `traces:` — confmap merges maps by key, so it added a *third* pipeline beside it, and both exported locally. Measured in the user's own Tempo: a trace with 46 spans of which 23 were unique, every span id twice. | **Fixed** — renamed back to `traces:`. Verified in an isolated collector: 2 trace pipelines, not 3. This was a regression this change introduced, and it is the same merge trap the overlay's own header warns about for lists, one level up. |
| M2 | **The export script's "refuse to write" guard wrote the file first.** It rendered, wrote, then checked and exited — leaving the leaked artefact on disk, ready for `git add`. | **Fixed** — render, check, then write. Verified: on refusal the file does not exist. |
| M3 | **The scrubber stripped a key n8n 2.x no longer emits and left the one it does.** `versionId` is gone; `activeVersionId` (a per-instance UUID), `versionCounter` and `versionMetadata` are what it emits — and the leak check was a case-sensitive substring, so `activeVersionId` did not match `versionId`. Both committed definitions carried one. | **Fixed** — all four keys stripped, check lower-cased. Both workflows re-exported and confirmed clean. |
| M4 | **The guard checked key names and never values.** The reviewer defeated it: a node with an inline `Authorization: Bearer sk-REAL-SECRET-abc123` header — which is what the n8n UI produces when you type a header instead of attaching a credential — exported clean, secret included. | **Fixed** — header, query and body parameter *values* are scanned for known secret header names and token-shaped literals. Reproduced the reviewer's attack: now refused, and nothing written. |
| M5 | **The compose test asserted agreement, never values.** Flipping `N8N_AGENTS_TRACING_RECORD_INPUTS/OUTPUTS`, the cardinality labels, or `N8N_OTEL_TRACES_PRODUCTION_ONLY` on **both** services kept the suite green — three spec requirements with zero coverage, in the one file whose stated purpose is to close that gap. The privacy one is the worst: it would ship prompts and model output outward. | **Fixed** — four value assertions added. The reviewer's exact mutations now go red. |
| M6 | **The rewritten dashboard had never rendered**, and its new panel had `datasource: null` with no default datasource configured. Grafana was still serving the pre-change JSON, placeholder panel and all, because the `lgtm` bind mount was empty inside the container. | **Fixed** — explicit `prometheus` datasource on panel and target, placeholder description replaced, `lgtm` recreated. Grafana now serves version 2 with all four panels and their datasources. The change-1 lesson about `--force-recreate` was applied to the Collector and not to Grafana. |

## Minors

Fixed: the truncation bound was asserted as `< 500` rather than at 128, and the
`is_recording()` guard was not asserted at all — both now mutation-checked; the
digest Code node had no null guard on `risk_score`, which would throw on a lift
the run skipped, and skipping is a first-class outcome of that very run; the
`n8n/workflows/README.md` import recipe produced the exact `Credentials not
found` failure `n8n-import-workflow.sh` exists to prevent, and never mentioned
that script; `.gitignore`'s blanket `*.png` silently refused to add the two
images this milestone exists to produce; the compose file and docs now state
that `--profile queue` without `N8N_EXECUTIONS_MODE=queue` yields a main process
in regular mode and an idle worker, with nothing reporting the mismatch; the
import spec scenario claimed the CLI reports missing credentials, which it does
not — reworded to what actually happens, with the execution-time failure as its
own scenario.

Also corrected: `README.md` still read "implementation not started"; the proposal
declared `observability` a modified capability and shipped **no delta spec**, so
`/archive` would have synced those requirements to the wrong capability — the
delta now exists; the proposal's file list was stale; `tasks.md` described the
ingest chain in the wrong order; and 13.5 was ticked with no report behind it.

## The Question, answered in the docs

`retryOnFail` covers node-level retry, which is what the idempotency guarantee
rests on. **"Retry execution → from the beginning"** re-runs the Code node and
mints a fresh `recorded_at`, so those readings are new identities and are stored.
The backend is not wrong to store them; the operator should retry the node.
Now stated in `docs/orchestration.md`.

## What the reviewer verified and found sound

Ingest idempotency and the token guard against the running stack; units (2590
rows, no Kelvin); the distributed trace and the middleware end to end, including
that `FastAPIInstrumentor` wraps the whole middleware stack so the server span is
always current — a suspicion they raised and then disproved by reading the
installed source; the OTTL filter condition itself; prod compose untouched; the
six-day trend; `.env` ignored; and that a Code node cannot read
`process.env.AWS_SECRET_ACCESS_KEY` (`process is not defined`).

They also **ran the retry test task 9.2 claimed and did not do** — a probe
workflow against a server that 500s once — and it passes: both attempts submitted
`recorded_at` `2026-09-01T05:52:00.097Z`, identical. The design was right; the
evidence had been an assumption stated as fact.

## After the fixes

- **232 passed** (was 226), coverage 96%, `ruff check` clean.
- Mutations re-run per task 18.3: all five reviewer-identified survivors now go
  red, plus the earlier five.
- Steps 13 and 14 executed and reported; step 15 recorded N/A where it belongs.

## Still open

Screenshots (tasks 4.6 and 10.4) need the editor UI and a browser. `.gitignore`
no longer blocks them.
