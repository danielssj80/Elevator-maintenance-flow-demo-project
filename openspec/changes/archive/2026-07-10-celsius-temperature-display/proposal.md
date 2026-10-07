# Proposal: celsius-temperature-display

## Why

The two temperature explainability features (Ambient temperature, Motor temperature) are
shown to users in **Kelvin** (e.g. `"298 K (−2.0 K, within range)"`) — an artefact of the
AI4I dataset units. For a maintenance UI, **°C** is the natural, readable unit.

## What Changes

- In `generate_predictions.py::_format_value`, format the Air/Process temperature `value`
  strings in °C (`raw − 273.15`). A delta is a difference, so its magnitude is unchanged;
  only the absolute reading is offset. Result: `"25°C (−2.0°C, within range)"`.
- Regenerate `predictions.json` (only the 76 temperature `value` strings change;
  `direction`, `impact`, names and `last_visit_date` are preserved).
- Add an Alembic data migration that resyncs the feature rows in place by elevator PK
  (same pattern as prior resyncs, preserving `visit_reports`).

No model retraining, no schema change, no API/frontend change (the `value` is a display
string rendered as-is). `impact` and `direction` semantics unchanged.

## Impact

- `backend/ml/generate_predictions.py`, regenerated `backend/ml/predictions.json`,
  one new `backend/alembic/versions/*.py`.
- No docs change needed (the API/data-model `value` examples are non-temperature).
- Deploy is a normal push to `main`; the `migrate` service resyncs before the backend starts.
