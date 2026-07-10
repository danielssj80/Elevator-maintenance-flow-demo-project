# Change: motor-life-feature

| Field | Value |
|---|---|
| **Status** | In progress |
| **Milestone** | M1 — Dataset & Model |
| **Corrects** | [`ml-offline-training`](../archive/2026-07-09-ml-offline-training/) (archived 2026-07-09) |
| **Branch** | `feature/motor-life-feature` |
| **Started** | 2026-07-10 |

## Summary

Fixes a feature-synthesis defect discovered in production after `ml-offline-training`
shipped: the AI4I `Tool wear [min]` input was computed as
`days_since_service × hourly_trips_avg × 1.5` and then hard-clamped to the dataset's
`[0, 253]` range. Because that product is 5–50× the ceiling for almost every elevator,
the clamp saturated ~57 of 70 in-scope units at the maximum (253 min ≈ "4 hrs"),
which is exactly AI4I's tool-end-of-life / failure region — so the model flagged
"high operating hours" as the dominant risk driver across most of the fleet.

This change replaces the saturating clamp with a proper domain-anchored scaling: the
elevator's **cumulative motor run-hours over its whole life** as a fraction of a
motor's rated life before failure (~40,000 operating hours). The user-facing feature
is reframed from "operating hours since service" to **"Motor useful life remaining (%)"**,
which is both more interpretable and more physically correct (motor failure is driven
by cumulative lifetime wear, not time since the last visit).

The trained model (`model.joblib`) does **not** change — only the offline feature
synthesis in `generate_predictions.py`, the regenerated `predictions.json`, and a new
resync migration.

## Artifacts

- [proposal.md](./proposal.md) — why and what changes
- [design.md](./design.md) — the reference value, the new formula, display framing, ADRs
- [tasks.md](./tasks.md) — implementation task list
