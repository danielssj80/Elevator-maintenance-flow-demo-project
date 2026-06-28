"""
Offline training script for the elevator failure-risk model.

Usage (from repo root):
    python backend/ml/train.py

Requires:
    backend/ml/data/ai4i2020.csv  (download from UCI or Kaggle)

Produces:
    backend/ml/model.joblib
"""

from __future__ import annotations

import pathlib
import sys

import joblib
import pandas as pd
from sklearn.metrics import classification_report, roc_auc_score
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier

ROOT = pathlib.Path(__file__).parent
DATA_PATH = ROOT / "data" / "ai4i2020.csv"
MODEL_PATH = ROOT / "model.joblib"

DROP_COLS = ["UDI", "Product ID", "TWF", "HDF", "PWF", "OSF", "RNF"]
TARGET = "Machine failure"


def load_and_prepare(path: pathlib.Path) -> tuple[pd.DataFrame, pd.Series]:
    df = pd.read_csv(path)

    # Normalise column name variants across dataset versions
    df.columns = df.columns.str.strip()
    if "Machine failure" not in df.columns and "Machine Failure" in df.columns:
        df = df.rename(columns={"Machine Failure": "Machine failure"})

    y = df[TARGET].astype(int)
    df = df.drop(columns=[c for c in DROP_COLS if c in df.columns] + [TARGET])

    # One-hot encode Type (L/M/H) → Type_M, Type_H (drop_first removes Type_L)
    df = pd.get_dummies(df, columns=["Type"], drop_first=True)

    # XGBoost rejects feature names containing [ ] or < — sanitise
    df.columns = [c.replace("[", "_").replace("]", "_").replace(" ", "_").strip("_") for c in df.columns]

    return df, y


def train(data_path: pathlib.Path = DATA_PATH) -> None:
    if not data_path.exists():
        print(f"ERROR: dataset not found at {data_path}", file=sys.stderr)
        print("Download ai4i2020.csv from UCI or Kaggle and place it there.", file=sys.stderr)
        sys.exit(1)

    print(f"Loading dataset from {data_path} …")
    X, y = load_and_prepare(data_path)
    print(f"  {len(X)} rows · {X.shape[1]} features · {y.sum()} positives ({y.mean():.1%})")

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=42
    )

    neg, pos = (y_train == 0).sum(), (y_train == 1).sum()
    model = XGBClassifier(
        scale_pos_weight=neg / pos,
        random_state=42,
        eval_metric="logloss",
        verbosity=0,
    )

    print("Training XGBClassifier …")
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    y_prob = model.predict_proba(X_test)[:, 1]

    print("\n── Test-set evaluation ──────────────────────────")
    print(classification_report(y_test, y_pred, digits=3))
    print(f"ROC-AUC: {roc_auc_score(y_test, y_prob):.4f}")
    print("─────────────────────────────────────────────────\n")

    joblib.dump(model, MODEL_PATH)
    print(f"Model saved to {MODEL_PATH}")
    print(f"Feature columns: {list(X.columns)}")


if __name__ == "__main__":
    train()
