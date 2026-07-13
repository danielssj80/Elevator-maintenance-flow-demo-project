# Tasks: celsius-temperature-display

## Status: ready

## Task list

### T1 — Format temperatures in °C + regenerate ✅

**Files:** `backend/ml/generate_predictions.py`, `backend/ml/predictions.json`

- `_format_value`: Air/Process temperature → `f"{raw - 273.15:.0f}°C ({sign}{abs(delta):.1f}°C, {qualifier})"`.
- Regenerate; merge only the temperature `value` strings onto the committed artifact to
  preserve `last_visit_date` and `direction` (avoids the unrelated date-drift diff).
- **Done:** 76 temperature values now in °C (e.g. ELV-073 Ambient `25°C (−2.0°C, within range)`);
  only `value` strings changed; dates/direction preserved.

---

### T2 — Alembic resync migration ✅

**Files:** `backend/alembic/versions/56cd241fcfd6_resync_features_celsius.py`

- `down_revision = "97f03bcd4e85"`; data-only (no schema change).
- Delete + reinsert feature rows per elevator PK from `predictions.json`
  (name/impact/value/direction); `visit_reports` untouched.
- **Done:** sqlite dry-run → 210 features, 76 °C values, 0 leftover K, `visit_reports` preserved.

---

### T3 — Verify

- Track B (local/prod): after deploy, `curl /api/elevators/ELV-073` shows temperature
  features in °C; detail view renders °C. Adversarial review before archive.

---

### T4 — Fix: nl_explanation also to °C (post-merge follow-up) ✅

**Files:** `backend/ml/predictions.json`, `backend/alembic/versions/aa3f0fc81e9c_resync_nl_explanation_celsius.py`

The T1/T2 pass converted feature `value` strings but not `elevators.nl_explanation` (a
separate string embedding the same values), so the "Model explanation" panel still showed
Kelvin in production after PR #22 merged. Because 56cd241fcfd6 had already run, it can't be
edited — a **new** migration is required.

- `predictions.json`: re-merge the °C `nl_explanation` (dates preserved; features already °C).
- Migration `aa3f0fc81e9c` (`down_revision = 56cd241fcfd6`): UPDATE `elevators.nl_explanation`
  per PK from `predictions.json`.
- **Done:** sqlite dry-run → 0 leftover K in nl_explanation.
