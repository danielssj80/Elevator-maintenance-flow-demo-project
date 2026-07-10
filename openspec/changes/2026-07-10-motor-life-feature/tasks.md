# Tasks: motor-life-feature

## Status: ready

## Task list

### T0 — Setup: feature branch

- [ ] 0.1 Work on branch `feature/motor-life-feature` (already created from `main`)
- [ ] 0.2 Verify with `git branch --show-current`

---

### T1 — Rework the operating-hours feature synthesis

**What:** Replace the saturating `days_since_service × trips × 1.5` clamp in
`_synthesise_features` with the fraction-of-motor-life scaling from `design.md`.

**Files changed:** `backend/ml/generate_predictions.py`

**Key points:**
- Add module constants `MAX_MOTOR_HOURS = 40_000.0`, `MOTOR_RUN_MIN_PER_TRIP = 0.4`,
  `ACTIVE_HOURS_PER_DAY = 16`.
- Compute `life_run_hours` from `age_years` + `hourly_trips_avg`; `fraction_consumed =
  min(1.0, life_run_hours / MAX_MOTOR_HOURS)`; `tool_wear = fraction_consumed * 253`.
- `_synthesise_features` needs `age_years` — thread it through from `_build_fleet_meta`
  (the callers already have the elevator dict; pass `age_years=e["age_years"]`).
- `push_to_failure` path: draw `fraction_consumed` from `Uniform(0.85, 0.97)`.

**Acceptance:** synthesised `Tool_wear__min` values span a wide range (not all ≈ 253);
spot-check that a young/light unit is low and an old/heavy unit is high.

---

### T2 — Reframe the display as "Motor useful life remaining (%)"

**What:** Change the feature name and value formatting.

**Files changed:** `backend/ml/generate_predictions.py`

**Key points:**
- `FEATURE_NAME_MAP["Tool_wear__min"] = "Motor useful life remaining"`.
- `_format_value` branch for `Tool_wear__min`: `remaining = round((1 - raw/253) * 100)`;
  return `f"{remaining}% remaining"` (append `" (critical)"` when `remaining < 20`).
- Remove the now-unused `Tool_wear__min` entry from `FEATURE_MEANS` (or leave with a note).

**Acceptance:** feature `value` strings read like `"81% remaining"`; no `"N hrs (high)"`
strings remain in `predictions.json`.

---

### T3 — Regenerate predictions.json and verify distribution

**What:** Run `python backend/ml/generate_predictions.py`; inspect output.

**Files changed:** `backend/ml/predictions.json`

**Acceptance:**
- 100 entries; in-scope entries have 3 features, impacts sum 0.99–1.01, non-empty
  `nl_explanation`, 6-point trend; out-of-scope entries have `features:[]` / `trend:[]`.
- At least 1 unit with `risk_score > 0.80` (high-risk guarantee).
- "Motor useful life remaining" is **no longer** shown as "high/critical" across most of
  the fleet — the majority of units show a healthy remaining % (e.g. > 60 %). Capture the
  before/after counts (saturated-at-max count should drop from 57/70 to a small number).
- Running twice produces identical output.

---

### T4 — Add resync migration

**What:** New Alembic data migration mirroring `0aac4958720e` (in-place UPDATE by PK +
full replace of features/trend_points), reading the regenerated `predictions.json`.

**Files changed:** `backend/alembic/versions/<rev>_resync_motor_life_feature.py`

**Acceptance:** `down_revision` points at `0aac4958720e`; dry-run against a simulated
stale DB (sqlite, as before) shows 100 rows updated in place, `visit_reports` untouched,
feature values reflecting the new remaining-% strings.

---

### T5 — Update docs

**What:** Update `docs/data-model.md` — the `Feature.value` example and/or the ML-derived
fields note — to mention the "Motor useful life remaining (%)" framing.

**Files changed:** `docs/data-model.md`

**Acceptance:** doc mentions the new feature framing; no unrelated content changed.

---

### T6 — Verify (local, Track B) + adversarial review

**What:** Per the two-track workflow, real-Postgres verification runs locally / dev-EC2:
`docker compose up --build`, then `curl /api/elevators/{id}` on a high-risk and a
mid-risk unit to confirm the new feature strings and that the fleet is no longer
uniformly "high hours". Then an independent `/adversarial-review` pass before archive.

**Acceptance:** detail responses show "Motor useful life remaining"; no regressions in the
pytest suite; adversarial review verdict recorded.
