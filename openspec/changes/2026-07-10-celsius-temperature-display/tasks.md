# Tasks: celsius-temperature-display

## Status: ready

## Task list

### T1 — Format temperatures in °C + regenerate ✅

**Files:** `backend/ml/generate_predictions.py`, `backend/ml/predictions.json`

- `_format_value`: Air/Process temperature → `f"{raw - 273.15:.0f}°C ({sign}{abs(delta):.1f}°C, {qualifier})"`.
- Regenerate; merge the temperature `value` strings **and** the `nl_explanation` (which
  embeds those values) onto the committed artifact to preserve `last_visit_date` and
  `direction` (avoids the unrelated date-drift diff).
- **Done:** 76 temperature values + the nl_explanation now in °C (e.g. ELV-025 Motor
  `37°C`, and its Model explanation reads °C too); dates/direction preserved.

---

### T2 — Alembic resync migration ✅

**Files:** `backend/alembic/versions/56cd241fcfd6_resync_features_celsius.py`

- `down_revision = "97f03bcd4e85"`; data-only (no schema change).
- UPDATE `elevators.nl_explanation` **and** delete + reinsert feature rows per elevator PK
  from `predictions.json` (name/impact/value/direction); `visit_reports` untouched.
- **Done:** sqlite dry-run → 0 leftover K in both nl_explanation and feature values,
  `visit_reports` preserved.

---

### T3 — Verify

- Track B (local/prod): after deploy, `curl /api/elevators/ELV-073` shows temperature
  features in °C; detail view renders °C. Adversarial review before archive.
