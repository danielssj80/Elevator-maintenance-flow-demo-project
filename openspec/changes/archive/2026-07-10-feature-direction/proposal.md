# Proposal: feature-direction

## Why

The "Prediction drivers" UI (`FeatureBar`) renders each factor's `impact` (= normalised
`|SHAP|`) as a weight bar, but the **sign** of the SHAP value is dropped. So a factor that
actually *reduces* risk appears in the drivers list as if it *contributes* to it.

Concrete case (production, ELV-073, risk 1.00): the motor is healthy — **"Motor useful
life remaining: 97% remaining"** — yet it shows in the top-3 with 14% weight. The real
driver is Load torque (+32 Nm above avg); the 97% motor life is *protective*, but the UI
can't tell the user that. The voice briefing reads fine (the LLM has context); only the
visual bars lack direction.

## What Changes

- Persist the SHAP **direction** per feature: `"increases"` (SHAP > 0, pushes toward
  failure) or `"decreases"` (SHAP < 0, protective). The sign is already computed in
  `generate_predictions.py::_shap_features`; it is currently discarded when taking
  `|SHAP|`.
- Add a `direction` field to the `Feature` domain object end-to-end: `predictions.json`,
  the `elevator_features` table (new column), the ORM model, the Pydantic schema, and the
  OpenAPI spec.
- Render it in the frontend `FeatureBar`: an arrow + colour (↑ red = raises risk, ↓ green =
  lowers risk) so protective factors are visually distinct from risk drivers.
- Migration: add the column and repopulate feature rows from the regenerated
  `predictions.json` (in-place by elevator PK, preserving `visit_reports`).

The model is **not** retrained. `impact` semantics are unchanged (still normalised
`|SHAP|` magnitude); `direction` is purely additive.

## Capabilities

### Modified Capabilities

- `elevator-explainability`: each `feature` now carries a `direction` (`increases` /
  `decreases`) indicating whether the factor pushes the risk score up or down, derived from
  the sign of its SHAP value. `name`, `impact`, and `value` are unchanged.

## Impact

- **Backend**: `backend/ml/generate_predictions.py`, regenerated `predictions.json`,
  `backend/app/models/elevator.py` (ORM column), `backend/app/schemas/elevator.py`,
  `backend/app/seed.py`, one new Alembic migration (schema + data).
- **Frontend**: `frontend/src/types/elevator.ts`, `frontend/src/components/FeatureBar.tsx`.
- **API**: additive field on `Feature` (`docs/api-spec.yml`).
- **Data model**: new `Feature.direction` (`docs/data-model.md`); `elevator_features` gains
  a `direction` column.
- **Model / AWS**: no changes. Deploy is a normal push to `main`; the `migrate` service adds
  the column and resyncs before the backend starts.
