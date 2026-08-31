# Adversarial Review — telemetry-ingestion-inference

- **Date**: 2026-08-30
- **Change**: telemetry-ingestion-inference
- **Branch**: `feature/telemetry-ingestion-inference`
- **Reviewer**: the implementing agent — **not independent**

## Independence caveat

The skill specifies a different agent or session from the one that implemented
the change. This pass was run by the implementing session, so it inherits every
assumption that produced the code. On the previous change, the findings that
mattered came from sessions with no prior context; two of the three blockers
there were invisible to the implementing agent. **This report does not
substitute for that round.**

## Sources

- `proposal.md`, `design.md`, `tasks.md`
- `specs/telemetry-ingestion/spec.md`, `specs/risk-inference/spec.md`
- `git diff main..feature/telemetry-ingestion-inference`
- The running compose stack, for the concurrency probe

## Method

Mutation claims in `tasks.md` were re-run rather than trusted, per the review
brief. Two were spot-checked in full (`6.3` production gate, `11.1` Kelvin
conversion) and both reproduced. The new guards introduced during this review
were mutated in turn.

## Findings

| Severity | Area | Finding | Evidence | Fix |
|---|---|---|---|---|
| **Major** | Concurrency | Two overlapping runs both read `last_scored_at` before either commits, both take the new-day branch, and the trend window advances twice for one day — a literal violation of the date-change requirement, in the exact scenario it exists to protect (a manual demo trigger landing on the schedule) | Two concurrent `POST /api/inference/run` on the live stack: both 200, both `scored: 14`, both new-day | **Code + spec.** `pg_advisory_xact_lock` held for the transaction. Re-measured: second run waits (0.464s vs 0.205s), window advances once. Requirement added to `specs/risk-inference` |
| **Major** | Robustness | An all-zero contribution vector raised an unhandled `ZeroDivisionError` in `_top_features`, producing a 500 with a stack trace. The impact-sum guard in `_apply` was unreachable for that case, because the division happens first | Test written for task 11.11 failed with `ZeroDivisionError` instead of `FeatureBuildError` | **Code + spec.** Explicit `FeatureBuildError` when the top-three magnitudes sum to zero. Scenario added |
| **Major** | Task hygiene | Task 11.11 ("whole run in one transaction; a mid-run failure leaves the database unchanged") was marked `[x]` with **no test in existence** | `grep` for atomicity/rollback/partial in `test_inference_service.py` returned nothing | **Tests.** Two tests added; writing them is what surfaced the two Majors above |
| **Minor** | Spec accuracy | The atomicity requirement described "a single transaction" without saying where it comes from. The run opens no transaction of its own; the guarantee is that the request-scoped session commits only after the handler returns, which makes "the run must raise rather than return a summary" the actual load-bearing behaviour | `app/database.py` `get_db` | **Spec.** Requirement now states the mechanism and the raise-don't-swallow rule, and a mutation confirms the test catches a swallowed error |
| **Minor** | Timezone | Same-day detection compares UTC dates. A run just after local midnight in a non-UTC timezone may be classified as the previous UTC day | `_apply`, `now.date()` | **None for now.** Correct for a UTC-scheduled job; worth stating if the schedule ever becomes local |
| **Minor** | Validation | `recorded_at` is not bounded against the future. A producer with a skewed clock could insert readings that dominate every subsequent window | `schemas/telemetry.py` | **Follow-up.** Reject readings more than a small tolerance in the future |
| **Minor** | Error detail | The 422 for an all-invalid batch interpolates every rejected id into the message; a 1000-reading batch of unknown ids produces a very long response body | `telemetry_service.ingest` | **Follow-up.** Cap the list in the message |
| Question | Statement volume | A run issues ~4 statements per scored elevator (delete + insert for features and for trend) — ~280 in one transaction at 70 in-scope elevators | Trace: 29 DELETE, 28 INSERT, 14 UPDATE for 14 elevators | **None.** Fine at this scale, visible in the trace if it stops being fine. Batching now would be premature |

## Guards verified by mutation during this review

| Mutation | Result |
|---|---|
| `if environment != "production"` → `if True` | 2 tests red ✓ |
| Drop `+ KELVIN_OFFSET` from `Air_temperature__K` | 15 tests red ✓ |
| `if total == 0` → `if False` (new guard) | 1 test red ✓ |
| Swallow `FeatureBuildError` in the apply loop (new guard) | 1 test red ✓ |

## Spec and task alignment

Every scenario in both spec files now maps to at least one test. The two
scenarios added during this review (`degenerate contribution vector`,
`two overlapping runs`) were written after the defects, not before, and are
labelled as such in `tasks.md`.

The three corrections this change made to the plan — the Kelvin variance canary
that does not fire, the non-reproducibility of `predictions.json`, and the
missing `last_scored_at` column — are recorded in the artifacts rather than only
in commit messages.

## Verdict

**FAIL at the start of this pass** — three Majors, all now fixed and
mutation-checked. **PASS WITH GAPS** in the current state, where the gap is the
review itself: this was not an independent pass.

## Recommended next steps before archive

1. **Run an independent adversarial review** from a session with no context.
   Brief it to re-run mutations and to attack the concurrency and trend-window
   logic specifically, since that is where this pass found the most.
2. Register the three Minors marked "follow-up" as Notion backlog tasks.
3. Do not archive on this report alone.
