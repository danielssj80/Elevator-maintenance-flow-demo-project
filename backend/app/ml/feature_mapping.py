"""Feature mapping shared by the offline generator and the online inference path.

These definitions were duplicated nowhere and lived only in
``backend/ml/generate_predictions.py``. Copying them into ``app/`` would let the
same reading render a different displayed value online and offline — the risk
score would agree while the text beside it disagreed, and no test would catch
it. They live here instead, imported by both.

The module is under ``app/`` rather than under ``ml/`` because the Dockerfile
already does ``COPY app/ ./app/``: the runtime gets it for free, and the offline
script imports up into it rather than the runtime importing down into an
offline directory.

Nothing here loads a model, reads a file or touches the network, so importing it
costs nothing in either process.
"""

from __future__ import annotations

# ── Feature mapping ───────────────────────────────────────────────────────────

# Sanitised column names produced by train.py:
#   spaces → _, brackets → _, then strip("_") from both ends
# One-hot on Type (H/L/M sorted alphabetically) with drop_first drops H →
#   keeps Type_L and Type_M; Type_H is the implicit reference (both = 0)
#
# These seven names are the ENTIRE feature space the trained booster accepts.
# There is no vibration, motor-current, door-error or door-cycle input. The
# feature table in docs/data-model.md used to claim otherwise; it described a
# model that was never built.
FEATURE_NAME_MAP: dict[str, str] = {
    "Air_temperature__K":      "Ambient temperature",
    "Process_temperature__K":  "Motor temperature",
    "Rotational_speed__rpm":   "Motor speed",
    "Torque__Nm":              "Load torque",
    "Tool_wear__min":          "Motor useful life remaining",
    "Type_L":                  "Installation type (residential)",
    "Type_M":                  "Installation type (commercial)",
}

# Dataset means (approximate, from AI4I 2020 documentation). Tool_wear is intentionally
# absent: its feature is displayed as remaining-life %, which needs no dataset mean.
FEATURE_MEANS: dict[str, float] = {
    "Air_temperature__K":     300.0,
    "Process_temperature__K": 310.0,
    "Rotational_speed__rpm":  1538.8,
    "Torque__Nm":             39.99,
    "Type_L":                 0.6,
    "Type_M":                 0.3,
}

# ── Motor-life model ──────────────────────────────────────────────────────────
MAX_MOTOR_HOURS = 40_000.0

# Per building type: (motor run-minutes per trip, active hours/day feeding hourly_trips_avg).
# Heavy-use buildings (infrastructure = metro/airport/hospital) consume life faster.
RUN_PARAMS: dict[str, tuple[float, int]] = {
    "residential":    (0.2, 8),
    "commercial":     (0.4, 10),
    "office":         (0.4, 10),
    "infrastructure": (1.5, 16),
}

RISK_ADJ = {"high": "High", "medium": "Moderate", "low": "Low"}


# ── Shared helpers ────────────────────────────────────────────────────────────

def risk_level(score: float) -> str:
    if score > 0.80:
        return "high"
    if score >= 0.50:
        return "medium"
    return "low"


def format_value(col: str, raw: float, shap_val: float) -> str:
    mean = FEATURE_MEANS.get(col, 0.0)
    delta = raw - mean
    direction = shap_val > 0  # True = pushes toward failure

    if col in ("Air_temperature__K", "Process_temperature__K"):
        # Convert absolute temperature K -> °C for display. A delta is a difference, so its
        # magnitude is identical in K and °C — only the absolute reading is offset by 273.15.
        sign = "+" if delta >= 0 else "−"
        qualifier = "above avg" if direction else "within range"
        return f"{raw - 273.15:.0f}°C ({sign}{abs(delta):.1f}°C, {qualifier})"
    if col == "Rotational_speed__rpm":
        qualifier = "high RPM" if direction else "normal"
        return f"{raw:.0f} rpm ({qualifier})"
    if col == "Torque__Nm":
        sign = "+" if delta >= 0 else "−"
        qualifier = "above avg" if direction else "within range"
        return f"{raw:.1f} Nm ({sign}{abs(delta):.1f} Nm, {qualifier})"
    if col == "Tool_wear__min":
        # raw is tool_wear in [0,253]; invert to remaining motor life as a percentage.
        remaining = round((1.0 - raw / 253.0) * 100)
        return f"{remaining}% remaining" + (" (critical)" if remaining < 20 else "")
    if col in ("Type_L", "Type_M"):
        return "yes" if raw > 0.5 else "no"
    return f"{raw:.2f}"


def nl_explanation(level: str, features: list[dict]) -> str:
    f = features
    return (
        f"{RISK_ADJ[level]} risk: {f[0]['name']} ({f[0]['value']}) is the primary "
        f"driver, combined with {f[1]['name']} ({f[1]['value']}) and "
        f"{f[2]['name']} ({f[2]['value']})."
    )
