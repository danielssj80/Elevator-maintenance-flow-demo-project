# Proposal: motor-life-feature

## Why

`ml-offline-training` (archived) synthesises one AI4I feature vector per elevator to
feed the trained model. Its `Tool wear [min]` rule is:

```python
tool_wear = days_since_service * hourly_trips_avg * 1.5
tool_wear = max(0.0, min(253.0, tool_wear))
```

AI4I `Tool wear` has a real physical range of `[0, 253]` min (a cutting tool's life),
and values near the top of that range are a strong failure signal (the OSF /
overstrain-failure mode). But `days_since_service × trips × 1.5` produces 1,000–14,000
for essentially every unit — 5–50× the ceiling — so the `min(253, …)` clamp pins
almost the whole fleet at 253. Measured on the deployed `predictions.json`:

- "Operating hours since service" appears as a top-3 driver in **67 / 70** in-scope units.
- It is shown as **"(high)"** (i.e. saturated at ~4 hrs) in **57 / 70**.
- It is the **#1** driver in **36 / 70**.

The clamp destroys all variance and drops most of the fleet into AI4I's failure region,
which is why the demo shows "high operating hours" as the dominant driver almost
everywhere. This is a correctness defect in how we adapt our domain to the pretrained
model, not a property of the model itself.

Conceptually, "hours in service" for an elevator is not continuous run-time, and time
since the last maintenance visit is not what wears a motor out — **cumulative lifetime
operating hours** is. So the fix also corrects the feature's meaning.

## What Changes

- Replace the saturating clamp in `generate_predictions.py::_synthesise_features` with a
  domain-anchored scaling: cumulative motor run-hours over the elevator's life, as a
  fraction of a motor's rated life before failure (~40,000 operating hours), mapped onto
  the AI4I `[0, 253]` domain. See `design.md` for the derivation and constants.
- Reframe the user-facing feature from `Operating hours since service` to
  **`Motor useful life remaining`**, displayed as a **percentage remaining**
  (100 % = new motor, ~15 % = failure region). `FEATURE_NAME_MAP` and the
  `_format_value` branch for this column change accordingly.
- Regenerate `backend/ml/predictions.json`.
- Add an Alembic data migration that resyncs the existing elevator rows in production
  (same in-place, PK-preserving pattern as `0aac4958720e`, to avoid the `visit_reports`
  cascade).
- Update `docs/data-model.md` (the `Feature.value` example / feature description) to
  mention the motor-life-remaining framing.

**No change** to `train.py`, `model.joblib`, the API surface, the DB schema, the frontend,
or AWS. The model is unchanged — only the offline feature vectors we feed it, and how we
present one feature, change.

## Capabilities

### Modified Capabilities

- `elevator-explainability`: the operating-hours risk factor is reframed as
  "Motor useful life remaining (%)", derived from the elevator's cumulative lifetime
  motor run-hours against a rated ~40,000-hour motor life, instead of a saturated
  "hours since service" value. `feature.impact` (normalised top-3 SHAP magnitude) and
  the overall response shape are unchanged.

## Impact

- **Modified files**: `backend/ml/generate_predictions.py`, `backend/ml/predictions.json`,
  `docs/data-model.md`, one new `backend/alembic/versions/*.py`
- **Model**: unchanged (`model.joblib` not retrained)
- **API / DB schema / frontend / AWS**: no changes
- **Fleet risk distribution**: overall risk scores drop for most units (most motors are
  nowhere near end-of-life), so the count of high-risk elevators will decrease from the
  current inflated 23. The high-risk guarantee (≥ 1 unit > 0.80) still holds. This is the
  intended, more-realistic behaviour; no specific distribution is targeted.
