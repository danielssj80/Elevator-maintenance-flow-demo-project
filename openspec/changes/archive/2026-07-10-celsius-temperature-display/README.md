# Change: celsius-temperature-display

| Field | Value |
|---|---|
| **Status** | In progress |
| **Milestone** | Backlog improvements |
| **Branch** | `feature/celsius-temperature-display` |
| **Started** | 2026-07-13 |

## Summary

Displays the two temperature explainability features (Ambient / Motor temperature) in **°C**
instead of Kelvin (an AI4I dataset artefact). Display-string only: `value` strings are
formatted in °C at generation, `predictions.json` regenerated, and a data migration resyncs
the feature rows. No model retraining, no schema/API/frontend change.

## Artifacts

- [proposal.md](./proposal.md)
- [tasks.md](./tasks.md)
