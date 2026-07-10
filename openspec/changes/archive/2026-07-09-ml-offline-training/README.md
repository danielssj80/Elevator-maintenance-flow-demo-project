# Change: ml-offline-training

| Field | Value |
|---|---|
| **Status** | Archived |
| **Milestone** | M1 — Dataset & Model |
| **Notion task** | [Train ML model offline on selected dataset](https://app.notion.com/p/36c3ada00a958134bd9fd76634d7b806) |
| **Branch** | `claude/dazzling-gates-eq35bx` (implementation, merged via PR #14) → `feature/archive-ml-offline-training` (archive) |
| **Started** | 2026-06-28 |
| **Merged to main** | 2026-07-09 (PR #14, squash) |
| **Archived** | 2026-07-09 |

## Summary

Replaces hardcoded risk scores and feature strings in `seed.py` with outputs from a real XGBoost model trained on the AI4I 2020 Predictive Maintenance dataset. SHAP values drive the explainability fields (`features`, `nl_explanation`). All outputs are pre-calculated offline and committed as `model.joblib` + `predictions.json` — no live inference endpoint is added.

## Artifacts

- [proposal.md](./proposal.md) — why and what changes
- [design.md](./design.md) — technical design, ADRs, code patterns
- [tasks.md](./tasks.md) — implementation task list (T1–T8)
