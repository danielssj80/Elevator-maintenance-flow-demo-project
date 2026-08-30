"""Model loading and scoring.

Contributions come from ``Booster.predict(..., pred_contribs=True)``, which
returns exact TreeSHAP values — the same quantity ``shap.TreeExplainer`` was
computing, from the library that owns the trees. That removes the ``shap``
dependency without approximating anything.

The booster's own ``feature_names`` is the authority on column order. Callers
send the order they used and it is checked, rather than trusted: a silently
transposed matrix produces a perfectly valid-looking score from the wrong
values, which is the failure mode this service exists to make impossible.
"""

from __future__ import annotations

import pathlib

import joblib
import numpy as np
import xgboost as xgb

MODEL_PATH = pathlib.Path(__file__).parent / "model.joblib"


class FeatureOrderMismatch(ValueError):
    """The caller's column order is not the booster's."""


class Scorer:
    def __init__(self, model_path: pathlib.Path = MODEL_PATH) -> None:
        self._model = joblib.load(model_path)
        self._booster = self._model.get_booster()
        self.feature_names: list[str] = list(self._booster.feature_names)
        # No versioning scheme exists for this artefact yet, so the file's own
        # content hash is the honest identifier: it changes when and only when
        # the model does.
        self.model_version: str = _content_hash(model_path)

    def score(
        self, feature_names: list[str], rows: list[list[float]]
    ) -> tuple[list[float], list[list[float]]]:
        if feature_names != self.feature_names:
            raise FeatureOrderMismatch(
                f"expected columns {self.feature_names}, received {feature_names}"
            )

        matrix = np.asarray(rows, dtype=float)
        if matrix.ndim != 2 or matrix.shape[1] != len(self.feature_names):
            raise FeatureOrderMismatch(
                f"expected rows of width {len(self.feature_names)}, "
                f"received shape {matrix.shape}"
            )

        scores = self._model.predict_proba(matrix)[:, 1]

        dmatrix = xgb.DMatrix(matrix, feature_names=self.feature_names)
        # pred_contribs returns one extra trailing column, the bias (the model's
        # expected value). It is not a feature, so it is dropped here rather
        # than left for every caller to remember.
        contribs = self._booster.predict(dmatrix, pred_contribs=True)[:, :-1]

        return scores.tolist(), contribs.tolist()


def _content_hash(path: pathlib.Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]
