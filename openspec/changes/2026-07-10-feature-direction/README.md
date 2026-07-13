# Change: feature-direction

| Field | Value |
|---|---|
| **Status** | In progress |
| **Milestone** | Backlog improvements |
| **Notion task** | [Show SHAP direction in feature bars](https://app.notion.com/p/3993ada00a9581909b71c8881e1e4841) |
| **Branch** | `feature/feature-shap-direction` |
| **Started** | 2026-07-10 |

## Summary

Adds a `direction` (`increases`/`decreases`) to each explainability `feature`, from the sign
of its SHAP value (currently discarded when taking `|SHAP|`). The frontend renders it as an
arrow + colour so protective factors (e.g. a healthy "Motor useful life remaining: 97%") are
visually distinct from risk drivers, instead of all appearing to contribute to risk. Model
not retrained; `impact` semantics unchanged.

## Artifacts

- [proposal.md](./proposal.md)
- [design.md](./design.md)
- [tasks.md](./tasks.md)
