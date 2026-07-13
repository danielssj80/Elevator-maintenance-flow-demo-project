# Tasks: feature-direction

## Status: ready

## Task list

### T0 — Setup: feature branch

- [x] 0.1 Work on branch `feature/feature-shap-direction` (created from `main`)
- [x] 0.2 Verify with `git branch --show-current`

---

### T1 — Emit `direction` in generate_predictions.py + regenerate ✅

**Files:** `backend/ml/generate_predictions.py`, `backend/ml/predictions.json`

- Add `"direction": "increases" if shap_vals[j] > 0 else "decreases"` to each feature dict
  in `_shap_features`.
- Regenerate `predictions.json`; verify each in-scope feature has a `direction`, output is
  reproducible, and known cases look right (e.g. ELV-073 "Motor useful life remaining" =
  `decreases`; "Load torque … above avg" = `increases`).

---

### T2 — Backend persistence (ORM + schema + seed) ✅

**Files:** `backend/app/models/elevator.py`, `backend/app/schemas/elevator.py`,
`backend/app/seed.py`

- `ElevatorFeature.direction: Mapped[str]`.
- `FeatureSchema.direction: str`.
- `seed.py`: `ElevatorFeature(..., direction=f["direction"])`.

---

### T3 — Alembic migration (add column + resync) ✅

**Files:** new `backend/alembic/versions/<rev>_add_feature_direction.py`

- `down_revision = "2c43876e02dd"`.
- `op.add_column("elevator_features", sa.Column("direction", sa.String(), nullable=False,
  server_default="increases"))`.
- Repopulate feature rows from `predictions.json` (delete + reinsert per elevator PK,
  including `direction`); `visit_reports` untouched.
- `downgrade`: `op.drop_column("elevator_features", "direction")`.
- **Acceptance:** sqlite dry-run — column added, features carry real directions,
  `visit_reports` preserved.

---

### T4 — API spec + data model docs ✅

**Files:** `docs/api-spec.yml`, `docs/data-model.md`

- Add `direction` (enum `increases`/`decreases`) to the `Feature` schema and mark required.
- Note the field in `docs/data-model.md` Feature table.

---

### T5 — Frontend rendering ✅

**Files:** `frontend/src/types/elevator.ts`, `frontend/src/components/FeatureBar.tsx`

- `Feature.direction: 'increases' | 'decreases'`.
- Render ↑ red (increases) / ↓ green (decreases) by the name; tint the weight bar to match.

---

### T6 — Review existing tests + verify ✅

**Files:** `backend/tests/**` (only if assertions break)

- Update any test that constructs `ElevatorFeature`/`FeatureSchema` without `direction`
  or asserts the `Feature` shape.
- Track B (local/prod): `docker compose up --build`; `curl /api/elevators/ELV-073` shows
  `direction` per feature and the UI renders arrows/colours. Adversarial review before
  archive.
