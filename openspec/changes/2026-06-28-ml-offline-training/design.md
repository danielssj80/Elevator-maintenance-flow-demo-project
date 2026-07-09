# Design: ml-offline-training

## Architecture

```
[Developer machine]
    train.py
        ↓  AI4I 2020 CSV (backend/ml/data/ai4i2020.csv)
        ↓  XGBClassifier (scale_pos_weight, random_state=42)
        → model.joblib

    generate_predictions.py
        ↓  model.joblib
        ↓  synthesised fleet features (from seed.py metadata, seed=42)
        ↓  model.predict_proba  → risk_score per elevator
        ↓  shap.TreeExplainer   → top-3 SHAP values per elevator
        → predictions.json

[Git commit]
    backend/ml/model.joblib
    backend/ml/predictions.json

[Docker build → seed_database()]
    seed.py loads predictions.json
        → Elevator rows with real risk_score, features, nl_explanation, trend
```

## Dataset: AI4I 2020

**Source:** UCI ML Repository (`ai4i2020.csv`, 10 000 rows, 14 columns)
**Target:** `Machine Failure` (binary) — positive rate ~3.4 %

**Features retained (6):**

| Column | Role |
|---|---|
| `Air temperature [K]` | Continuous input |
| `Process temperature [K]` | Continuous input |
| `Rotational speed [rpm]` | Continuous input |
| `Torque [Nm]` | Continuous input |
| `Tool wear [min]` | Continuous input |
| `Type` | Categorical (L/M/H) → one-hot (2 cols after drop_first) |

**Dropped:** `UDI`, `Product ID`, `TWF`, `HDF`, `PWF`, `OSF`, `RNF`

## Training (train.py)

```python
from xgboost import XGBClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, roc_auc_score
import joblib, pandas as pd

df = pd.read_csv("backend/ml/data/ai4i2020.csv")
# ... feature engineering ...
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, stratify=y, random_state=42
)
model = XGBClassifier(
    scale_pos_weight=(y == 0).sum() / (y == 1).sum(),
    random_state=42, eval_metric="logloss"
)
model.fit(X_train, y_train)
# log classification_report + roc_auc_score on test set
joblib.dump(model, "backend/ml/model.joblib")
```

Expected test-set performance: F1 ≥ 0.70, ROC-AUC ≥ 0.90 (based on published benchmarks).

## Feature synthesis (generate_predictions.py)

Each elevator's feature vector is synthesised from its metadata using `random.Random(42)`:

| AI4I feature | Synthesis rule |
|---|---|
| `Air temperature [K]` | `Normal(300, 2)` + 2 K if `building_type == infrastructure` |
| `Process temperature [K]` | `air_temp + Normal(10, 1)` |
| `Rotational speed [rpm]` | `2860/torque * 9549 + Normal(0, 50)`, clamped to [1168, 2860] |
| `Torque [Nm]` | `Normal(40, 10) + floor_count * 0.3`, clamped to [3, 80] |
| `Tool wear [min]` | `days_since_last_service * hourly_trips_avg * 1.5`, clamped to [0, 253] |
| `Type` (one-hot) | residential → L, commercial/office → M, infrastructure → H |

**High-risk guarantee:** After generating all 100 scores, if `max(risk_scores) < 0.80`, the script re-samples `Tool wear` and `Torque` for the 3 elevators with highest `age_years × hourly_trips_avg` by drawing from the top-quartile of those features in the training set, then re-predicts. This loop runs until at least 1 score exceeds 0.80 (typically 1–2 iterations). No upper cap on high-risk count — the distribution is otherwise entirely model-driven.

## SHAP explainability

```python
import shap

explainer = shap.TreeExplainer(model)      # built once after loading model
shap_values = explainer.shap_values(X_fleet)  # shape: (100, n_features)

for i, elevator in enumerate(fleet):
    sv = shap_values[i]                        # one value per feature
    top3_idx = np.argsort(np.abs(sv))[-3:][::-1]
    top3_abs = np.abs(sv[top3_idx])
    impacts = top3_abs / top3_abs.sum()        # normalise → sum = 1.0

    features = [
        {
            "name": FEATURE_NAME_MAP[col_names[j]],
            "impact": round(float(impacts[k]), 3),
            "value": format_value(col_names[j], X_fleet[i, j], sv[j], train_means)
        }
        for k, j in enumerate(top3_idx)
    ]
```

**`FEATURE_NAME_MAP`** (AI4I column → elevator display name):

| AI4I column | Display name |
|---|---|
| `Air temperature [K]` | `Ambient temperature` |
| `Process temperature [K]` | `Motor temperature` |
| `Rotational speed [rpm]` | `Motor speed` |
| `Torque [Nm]` | `Load torque` |
| `Tool wear [min]` | `Operating hours since service` |
| `Type_M` | `Installation type (commercial)` |
| `Type_H` | `Installation type (infrastructure)` |

**`format_value(col, raw, shap_val, means)`** returns a human-readable string:
- Positive SHAP (pushing toward failure): `"318 K (+8 K above avg)"`, `"4 200 hrs (high)"`
- Negative SHAP (pushing away from failure): `"292 K (−8 K, within range)"`, `"24 days (recent)"`

## nl_explanation template

```python
RISK_ADJ = {"high": "High", "medium": "Moderate", "low": "Low"}

nl_explanation = (
    f"{RISK_ADJ[risk_level]} risk: {features[0]['name']} ({features[0]['value']}) "
    f"is the primary driver, combined with {features[1]['name']} "
    f"({features[1]['value']}) and {features[2]['name']} ({features[2]['value']})."
)
```

## predictions.json schema

```json
[
  {
    "id": "ELV-001",
    "risk_score": 0.91,
    "risk_level": "high",
    "nl_explanation": "High risk: Motor temperature (318 K, +8 K above avg) is the primary driver, combined with Operating hours since service (4 200 hrs, high) and Load torque (58 Nm, +18 Nm above avg).",
    "features": [
      {"name": "Motor temperature",              "impact": 0.51, "value": "318 K (+8 K above avg)"},
      {"name": "Operating hours since service",  "impact": 0.31, "value": "4 200 hrs (high)"},
      {"name": "Load torque",                    "impact": 0.18, "value": "58 Nm (+18 Nm above avg)"}
    ],
    "trend": [0.55, 0.63, 0.71, 0.79, 0.86, 0.91]
  },
  ...
]
```

## seed.py integration

```python
import json, pathlib

_ML_DIR = pathlib.Path(__file__).parent.parent / "ml"
_PREDICTIONS: dict[str, dict] = {
    p["id"]: p
    for p in json.loads((_ML_DIR / "predictions.json").read_text())
}
```

In `_build_elevators()`, each elevator now reads:
```python
pred = _PREDICTIONS[eid]
risk_score    = pred["risk_score"]
risk_level    = pred["risk_level"]
nl_explanation = pred["nl_explanation"]
features      = [ElevatorFeature(**f) for f in pred["features"]]
trend_points  = [ElevatorTrendPoint(day_index=j, score=s) for j, s in enumerate(pred["trend"])]
```

The out-of-scope elevators (`in_model_scope=False`) keep placeholder values — they are not run through the model. The script marks them as `risk_score=null` / `risk_level=null` and `seed.py` handles them with a sentinel branch (same as today).

## Dependencies added to requirements.txt

```
xgboost>=2.0
shap>=0.45
```

`scikit-learn` and `joblib` are already present.

## Reproducibility contract

- `train.py`: `random_state=42` in `XGBClassifier` and `train_test_split`.
- `generate_predictions.py`: `random.Random(42)` for feature synthesis; SHAP is deterministic given a fixed model.
- Both `model.joblib` and `predictions.json` are committed — the Docker build never re-runs training.

## ADR: why not live inference?

**Decision:** pre-calculate predictions offline; commit JSON artifact; no inference endpoint.

**Rationale:** The demo fleet is static (100 fixed elevators). Live inference would add runtime dependencies (model loading, SHAP), increase cold-start time, and provide no benefit since there is no real telemetry stream. Pre-calculation keeps the backend simple, startup fast, and the deployment identical to what exists today. If real-time telemetry is ever integrated, a `/predict` endpoint can be added then.
