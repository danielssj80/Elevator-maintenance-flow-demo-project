# Tasks: ml-offline-training

## Status: ready

## Task list

### T1 — Add dependencies and ml/ directory scaffold

**What:** Add `xgboost` and `shap` to `backend/requirements.txt`. Create `backend/ml/` directory with a `.gitkeep` and `backend/ml/data/.gitignore` (to ignore the raw CSV but not the generated artifacts).

**Files changed:**
- `backend/requirements.txt` — add `xgboost>=2.0`, `shap>=0.45`
- `backend/ml/.gitkeep` — ensures directory is tracked
- `backend/ml/data/.gitignore` — ignore `*.csv` (dataset not committed), keep everything else

**Acceptance:** `pip install -r requirements.txt` succeeds; `backend/ml/` exists in git.

---

### T2 — Write train.py

**What:** Offline training script. Loads `backend/ml/data/ai4i2020.csv`, engineers features, trains XGBClassifier, evaluates, and exports `backend/ml/model.joblib`.

**Files changed:**
- `backend/ml/train.py` (new)

**Key implementation points:**
- Drop `UDI`, `Product ID`, `TWF`, `HDF`, `PWF`, `OSF`, `RNF`
- One-hot encode `Type` with `drop_first=True` (→ `Type_M`, `Type_H`)
- `train_test_split(stratify=y, test_size=0.2, random_state=42)`
- `XGBClassifier(scale_pos_weight=neg/pos, random_state=42, eval_metric="logloss")`
- Print `classification_report` and `roc_auc_score` on test set
- `joblib.dump(model, "backend/ml/model.joblib")`

**Acceptance (T2):** Script runs with `python backend/ml/train.py`; `model.joblib` is produced; test-set F1 printed to stdout.

---

### T3 — Write generate_predictions.py

**What:** Offline prediction generation script. Loads `model.joblib` and the elevator metadata from a standalone copy of the seed constants (building list, models, etc.), synthesises one feature vector per elevator, predicts `risk_score`, runs SHAP, assembles `features` and `nl_explanation`, generates `trend`, and writes `backend/ml/predictions.json`.

**Files changed:**
- `backend/ml/generate_predictions.py` (new)

**Key implementation points:**
- Import fleet metadata constants from `backend/app/seed.py` (or duplicate the necessary lists into the script to avoid circular imports)
- Feature synthesis per `design.md` synthesis rules, `random.Random(42)`
- High-risk guarantee loop: if `max(scores) < 0.80`, re-sample top-3 by `age_years × hourly_trips_avg`
- `shap.TreeExplainer(model)` — compute SHAP values for all 100 rows at once
- Top-3 by `|shap_value|`, normalise to sum = 1.0 for `impact`
- `FEATURE_NAME_MAP` and `format_value()` as specified in `design.md`
- `nl_explanation` deterministic template
- `_generate_trend()` logic (copy from seed.py or import)
- Out-of-scope elevators (`in_model_scope=False`): `risk_score=null`, `risk_level=null`, `nl_explanation=""`, `features=[]`, `trend=[0]*6`
- Write JSON with `json.dumps(fleet, indent=2)`

**Acceptance (T3):**
- `python backend/ml/generate_predictions.py` runs offline and produces `backend/ml/predictions.json`
- JSON has exactly 100 entries
- All in-scope entries have valid `risk_score`, 3 features with impacts summing to 0.99–1.01, non-empty `nl_explanation`, trend of 6 floats
- At least 1 entry has `risk_score > 0.80`
- Running twice produces identical output (reproducibility)

---

### T4 — Run scripts, commit artifacts

**What:** Execute `train.py` and `generate_predictions.py` locally, verify outputs, commit `model.joblib` and `predictions.json`.

**Steps:**
1. Download AI4I 2020 CSV to `backend/ml/data/ai4i2020.csv` (from Kaggle or UCI)
2. `python backend/ml/train.py` → verify F1 printed ≥ 0.70
3. `python backend/ml/generate_predictions.py` → verify JSON
4. `git add backend/ml/model.joblib backend/ml/predictions.json`

**Acceptance (T4):** Both files present in git; JSON passes manual spot-check (at least 1 high-risk elevator, features look sensible, nl_explanation references top feature name).

---

### T5 — Update seed.py to load from predictions.json

**What:** Replace hardcoded `NL_EXPLANATIONS`, `FEATURE_SETS`, `high_risk_scores`, and all `rng.uniform()` risk-score calls in `_build_elevators()` with data loaded from `predictions.json`.

**Files changed:**
- `backend/app/seed.py`

**Key implementation points:**
- Add module-level `_PREDICTIONS` dict keyed by elevator id (see `design.md`)
- In `_build_elevators()`, for each elevator: derive `risk_score`, `risk_level`, `nl_explanation`, `features`, `trend_points` from `_PREDICTIONS[eid]`
- Remove `NL_EXPLANATIONS`, `FEATURE_SETS`, `high_risk_scores` constants (no longer needed)
- Keep `_generate_trend()` removed or renamed — trend now comes from JSON
- Out-of-scope elevators: handle `risk_score=null` branch (set to `0.0`, `risk_level="low"`, empty features)

**Acceptance (T5):** `seed.py` imports cleanly; no references to old hardcoded constants remain.

---

### T6 — Smoke test: docker-compose up --build

**What:** Build and run the full stack; verify the seeded data reflects model outputs.

**Steps:**
1. `docker-compose up --build`
2. `curl http://localhost:8000/api/elevators` — check at least 1 elevator with `risk_score > 0.80`
3. `curl http://localhost:8000/api/elevators/ELV-001` — check `nl_explanation` and `features` are non-empty and reference real feature names (not old hardcoded strings like "Vibration anomaly")
4. Open frontend at `http://localhost:3000` — confirm detail view renders correctly with new data

**Acceptance (T6):** All AC-1 through AC-7 from the Notion task pass; no 500 errors on seed or API calls.

---

### T7 — Backend test suite: confirm no regressions

**What:** Run existing pytest suite to confirm the seed change does not break any existing tests.

**Files changed:** none (tests are not modified unless they break)

**Steps:**
1. `docker-compose run --rm backend pytest`
2. Fix any test that asserts specific hardcoded risk scores or feature strings

**Acceptance (T7):** All tests pass (or are updated with a comment explaining why the assertion changed).

---

### T8 — Update docs/data-model.md

**What:** Add a note in the "Current Data Storage" section clarifying that `risk_score`, `nl_explanation`, `features`, and `trend` are sourced from `backend/ml/predictions.json` (pre-calculated by `generate_predictions.py` using a trained XGBoost model).

**Files changed:**
- `docs/data-model.md`

**Acceptance (T8):** The note is present and accurate; no other content in the file is changed.
