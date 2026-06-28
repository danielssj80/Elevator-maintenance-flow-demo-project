# Proposal: ml-offline-training

## Why

The demo fleet currently runs on hardcoded, hand-crafted risk scores in `backend/app/seed.py`. Every score, explainability feature, and natural-language explanation is a static string chosen manually — there is no model behind them. Milestone **M1** replaces this fiction with outputs from a real binary classifier trained on a public industrial dataset, so the portfolio demo can honestly claim to show ML-driven predictive maintenance.

The approach is offline pre-calculation: training happens once on a developer machine, the outputs are committed to the repository, and the backend seed script loads them at startup. No live inference endpoint is added — the demo remains a static fleet that a visitor can explore, with the difference that the risk scores, SHAP-derived feature importances, and natural-language explanations now reflect a real trained model rather than editorial judgment.

## What Changes

- Add `backend/ml/train.py`: offline training script that downloads and trains an `XGBClassifier` on the AI4I 2020 Predictive Maintenance dataset (UCI/Kaggle), evaluates on a held-out test set, and exports `backend/ml/model.joblib`.
- Add `backend/ml/generate_predictions.py`: offline script that synthesises one feature vector per elevator (mapped from elevator metadata to AI4I feature space), runs `model.predict_proba` for the `risk_score`, runs `shap.TreeExplainer` for the top-3 contributing features, assembles `nl_explanation` from a deterministic template, generates the 6-day `trend` array, and writes `backend/ml/predictions.json`.
- Commit `backend/ml/model.joblib` and `backend/ml/predictions.json` to the repository so the Docker build is fully offline.
- Modify `backend/app/seed.py` to load risk scores, features, `nl_explanation`, and trend data from `predictions.json` instead of the current hardcoded constants. Building metadata, technicians, and zone assignments remain unchanged.
- Add `xgboost` and `shap` to `backend/requirements.txt`.

No API changes. No frontend changes. No database schema changes. The data model fields `risk_score`, `nl_explanation`, `features`, and `trend` already exist and are already consumed by the frontend correctly.

## Capabilities

### Modified Capabilities

- `elevator-risk-scores`: Risk scores for in-scope elevators are now produced by a trained XGBoost model rather than hardcoded constants. The scores are pre-calculated and loaded at seed time; the API contract and response shape are unchanged.
- `elevator-explainability`: The three risk factors (`features`) and `nl_explanation` for each elevator are now derived from SHAP values computed against the trained model, rather than assigned manually. `feature.impact` values are normalised top-3 SHAP magnitudes; `feature.value` strings represent the raw input value relative to the dataset mean; `nl_explanation` is a deterministic template populated from the top SHAP feature.

## Impact

- **New files**: `backend/ml/train.py`, `backend/ml/generate_predictions.py`, `backend/ml/model.joblib`, `backend/ml/predictions.json`, `backend/ml/data/ai4i2020.csv` (dataset, gitignored or committed TBD)
- **Modified backend files**: `backend/app/seed.py`, `backend/requirements.txt`
- **API**: no changes
- **Data model**: no schema changes — existing fields (`risk_score`, `nl_explanation`, `features`, `trend`) are populated from a different source
- **Docs**: `docs/data-model.md` — note that ML-derived fields are sourced from `predictions.json` in the "Current Data Storage" section
- **No frontend changes**
- **No AWS changes** — the Docker image already builds from the committed artifacts; deployment is a normal push to `main`
