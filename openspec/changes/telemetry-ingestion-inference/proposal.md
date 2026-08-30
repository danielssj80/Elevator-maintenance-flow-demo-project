# Proposal: telemetry-ingestion-inference

## Why

Risk scores in this system are a fiction produced once, offline. `backend/ml/generate_predictions.py` synthesises a feature vector per elevator, scores it, and writes `predictions.json`; `app/seed.py` loads that file into the database at startup. Nothing in the running system ever scores anything. There is no table for a sensor reading, no endpoint to submit one, and no code path from a reading to a score. The "predictive maintenance" claim currently rests entirely on a build-time artifact.

That gap blocks the rest of milestone M5. The n8n workflows in the next change have nothing to call: an ingest workflow needs somewhere to POST readings, and a daily inference workflow needs a job to trigger. It also caps the observability story from the previous change at a single service — the interesting distributed trace (`n8n → backend → inference → postgres`) does not exist because there is no third service.

Two verified facts about the existing model shape everything below, and either one silently corrupts the result if ignored:

- **The model's feature space is AI4I's 7 columns.** `generate_predictions.py:109` lists every input the booster accepts: `Air_temperature__K`, `Process_temperature__K`, `Rotational_speed__rpm`, `Torque__Nm`, `Tool_wear__min`, `Type_L`, `Type_M`. There is no vibration, motor-current, door-error or door-cycle input anywhere in the codebase. The "known feature names" table in `docs/data-model.md` documents a model that was never built, and designing the new table from that document would produce columns the model cannot consume.
- **The model was trained in Kelvin.** `Air_temperature__K ≈ 300`, `Process_temperature__K ≈ 310`. `generate_predictions.py:192` converts to °C for display only. A reading of `27` reaching `predict_proba` unconverted sends every tree down the same branch, so every elevator receives an identical, entirely plausible score — with no exception and no log line.

## What Changes

- Add `telemetry_readings`: a new table storing one sensor reading per elevator per timestamp, in human units (°C, rpm, Nm, hours), with ingest provenance (`source`, `batch_id`, `trace_id`).
- Add `POST /api/telemetry/readings` (batch ingest, max 1000, with plausible-range and no-future validation on the readings), `GET /api/telemetry/readings` (windowed query, bounded at both ends) and `POST /api/inference/run` (trigger a re-scoring run, serialised against concurrent runs).
- Add `backend/inference/`: a separate, stateless FastAPI service exposing `POST /score`. It is the only image that carries `model.joblib`. It uses `Booster.predict(..., pred_contribs=True)` for exact TreeSHAP, which makes the `shap` package redundant and removes the `shap → numba → llvmlite` dependency chain (~250 MB) from `requirements-ml.txt`, and therefore from the offline script and from the new service alike.
- Add `app/services/inference_client.py` (an httpx client structurally mirroring `BedrockClient`) and `app/services/inference_service.py` (window aggregation, Kelvin conversion, re-scoring, feature and trend persistence).
- Extract `FEATURE_NAME_MAP`, `FEATURE_MEANS`, `RUN_PARAMS`, `MAX_MOTOR_HOURS`, `_format_value`, `_risk_level` and `_nl_explanation` from `generate_predictions.py` into `backend/app/ml/feature_mapping.py`, imported by both the offline script and the online service, so the two cannot drift.
- Gate the telemetry and inference routers off when `deployment_environment == "production"`.
- Fix the stale feature list in `docs/data-model.md` and document `TelemetryReading`.

## Capabilities

### New Capabilities

- `telemetry-ingestion`: the system accepts and persists batches of elevator telemetry readings in human units, with provenance linking each row to the ingest trace that created it, tolerates unknown elevator ids within a batch, prunes readings beyond a retention window, and is not reachable in production.
- `risk-inference`: the system re-scores the in-scope fleet from persisted telemetry using the trained model behind a dedicated service, converting temperatures at exactly one boundary, skipping elevators with no data in the window, and maintaining the 6-day trend contract independently of how often the job runs.

### Modified Capabilities

- None. No existing requirement changes behaviour. The `GET /api/elevators` and `GET /api/elevators/{id}` response shapes are untouched — this change alters the *values* those endpoints serve, not their contract.

## Impact

- **New files**: `backend/app/models/telemetry.py`, `backend/app/repositories/telemetry_repository.py`, `backend/app/schemas/telemetry.py`, `backend/app/schemas/inference.py`, `backend/app/services/telemetry_service.py`, `backend/app/services/inference_service.py`, `backend/app/services/inference_client.py`, `backend/app/ml/__init__.py`, `backend/app/ml/feature_mapping.py`, `backend/app/routers/telemetry.py`, `backend/app/routers/inference.py`, `backend/alembic/versions/<rev>_create_telemetry_readings.py`, `backend/inference/` (Dockerfile, `main.py`, `scorer.py`, `requirements.txt`), and their tests.
- **Modified files**: `backend/app/main.py`, `backend/app/core/config.py`, `backend/ml/generate_predictions.py`, `backend/requirements.txt` (adds `httpx`, see below), `backend/requirements-ml.txt` (drops `shap`), `docker-compose.yml`, `docs/api-spec.yml`, `docs/data-model.md`, `docs/backend-standards.md`.
- **Not modified**: `docker-compose.prod.yml`. The inference service is dev-only and the new routers are gated off in production, so production behaviour is unchanged.
- **Frontend**: none. No response shape changes; the dashboard reads the same fields it reads today. The mandatory Playwright step is N/A.
- **Database**: one new table with two indexes, plus one nullable column on `elevators` (`last_scored_at`). That column was not foreseen when this proposal was written: the trend window shifts on date change, and `elevator_trend_points` stores only `day_index` and `score`, so a trend point cannot say which day it belongs to and the decision is not derivable from the trend itself. `elevator_features` and `elevator_trend_points` gain new *rows* during a run, not new columns.
- **Security**: `POST /api/telemetry/readings` and `POST /api/inference/run` are unauthenticated write endpoints, and `docker-compose.prod.yml` auto-deploys on merge to `main`. Production router-gating is a requirement of this change, not a follow-up.
- **Dependencies**: `httpx` is currently a *dev-only* dependency (`requirements-dev.txt`); nothing under `app/` imports it, and `opentelemetry-instrumentation-httpx` is installed without the library it instruments. `inference_client.py` needs it at runtime, so it moves into `requirements.txt` pinned to the version already used in dev. `shap` is removed from `requirements-ml.txt`. Neither `xgboost` nor `shap` was ever in the runtime image and neither enters it now — the model stays in the `inference` image alone.
- **Runtime cost**: one additional dev container (`inference`, no DB access, ~400 MB because it carries xgboost). The backend image is unchanged in size but for `httpx`.
