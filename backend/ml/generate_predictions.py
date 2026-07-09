"""
Offline prediction generation script.

Synthesises one feature vector per elevator, runs the trained XGBoost model
to produce risk_score, computes SHAP explanations, and writes predictions.json.

Usage (from repo root):
    python backend/ml/generate_predictions.py

Requires:
    backend/ml/model.joblib  (produced by train.py)

Produces:
    backend/ml/predictions.json
"""

from __future__ import annotations

import json
import pathlib
import random
import sys
from datetime import date, timedelta

import joblib
import numpy as np
import shap

ROOT = pathlib.Path(__file__).parent
MODEL_PATH = ROOT / "model.joblib"
OUTPUT_PATH = ROOT / "predictions.json"

# ── Fleet metadata (mirrors backend/app/seed.py) ──────────────────────────────

BUILDING_NAMES = [
    "Torre Picasso", "Edificio Azca", "Residencial Las Flores", "Centro Comercial Xanadú",
    "Hospital La Paz", "Aeropuerto T4", "Palacio de Congresos", "Residencial El Encinar",
    "Oficinas Castellana", "Hotel NH Collection", "Centro Médico Quirón", "Residencial Valdebebas",
    "Edificio España", "Torre Espacio", "Torre de Cristal", "Torre Caja Madrid",
    "Metro Sol", "Metro Nuevos Ministerios", "Centro Comercial La Vaguada", "Museo Reina Sofía",
    "Residencial Montecarmelo", "Edificio Beatriz", "Oficinas Manoteras", "Clínica Ruber",
    "Residencial Sanchinarro", "Torre Telefónica", "Centro Comercial Plenilunio", "Edificio Cuzco",
    "Residencial Carabanchel", "Colegio Mayor Bosch", "Oficinas Alcobendas", "Residencial Getafe",
    "Hospital Gregorio Marañón", "Edificio Generali", "Torre Agbar", "Residencial Poblenou",
    "Oficinas 22@", "Hospital Clínic", "Centro Comercial Diagonal Mar", "Edificio Mapfre",
    "Residencial Eixample", "Torre Glòries", "Metro L9 Aeroport", "Hospital Vall d'Hebron",
    "Oficinas Cornellà", "Residencial Sant Gervasi", "Centro Comercial Gran Via 2", "Edificio Fórum",
    "Residencial Les Corts", "Metro Sagrera", "Torre Sevilla", "Residencial Triana",
    "Hotel Alfonso XIII", "Centro Comercial Lagoh", "Edificio Viapol", "Hospital Virgen del Rocío",
    "Oficinas Palmas Altas", "Residencial Nervión", "Aeropuerto SVQ", "Metro Sevilla",
    "Torre BBVA Bilbao", "Residencial Abandoibarra", "Hospital Basurto", "Centro Comercial Zubiarte",
    "Edificio Iberdrola", "Metro Bilbao L1", "Oficinas Derio", "Residencial Getxo",
    "Centro Comercial Bulevar", "Torre KPMG Valencia", "Residencial Ruzafa", "Hospital La Fe",
    "Oficinas Parc Tecnològic", "Centro Comercial Aqua", "Metro Línea 5 Valencia", "Edificio Cánovas",
    "Residencial Benimaclet", "Torre Zaragoza", "Residencial Delicias", "Hospital Miguel Servet",
    "Centro Comercial Puerto Venecia", "Edificio CAI", "Metro Zaragoza", "Oficinas Plaza",
    "Residencial Actur", "Torre A Coruña", "Hospital CHUAC", "Centro Comercial Marineda City",
    "Edificio Fenosa", "Residencial Elviña", "Oficinas Polígono Pocomaco", "Metro Bilbao L2",
    "Residencial Santander Centro", "Hospital Marqués de Valdecilla", "Edificio Caja Cantabria",
    "Centro Comercial El Sardinero", "Torre Málaga", "Hospital Regional Málaga",
    "Residencial Teatinos", "Centro Comercial Málaga",
]

BUILDING_TYPES = ["residential", "commercial", "office", "infrastructure"]
BUILDING_TYPE_WEIGHTS = [0.5, 0.2, 0.2, 0.1]

ELEVATOR_MODELS = [
    ("ThyssenKrupp MAX 3000", "own", 2019),
    ("ThyssenKrupp Evolution", "own", 2017),
    ("ThyssenKrupp Synergy", "own", 2021),
    ("Otis Gen2", "third_party", 2015),
    ("Otis Infinity", "third_party", 2018),
    ("Kone EcoSpace", "third_party", 2016),
    ("Kone MonoSpace", "third_party", 2013),
    ("Schindler 3300", "third_party", 2014),
    ("Schindler 5500", "third_party", 2020),
    ("Legacy Unit A", "third_party", 2005),
    ("Legacy Unit B", "third_party", 2003),
    ("Legacy Unit C", "third_party", 2008),
]

TECHNICIANS = [
    "Carlos Martínez", "Ana García", "Javier López", "María Sánchez",
    "Pedro Fernández", "Laura González", "Miguel Rodríguez", "Elena Martín",
    "Roberto Díaz", "Isabel Pérez",
]

ZONES = ["Madrid", "Barcelona", "Sevilla", "Bilbao", "Valencia",
         "Zaragoza", "A Coruña", "Santander", "Málaga"]

# ── Feature mapping ───────────────────────────────────────────────────────────

# Sanitised column names produced by train.py:
#   spaces → _, brackets → _, then strip("_") from both ends
# One-hot on Type (H/L/M sorted alphabetically) with drop_first drops H →
#   keeps Type_L and Type_M; Type_H is the implicit reference (both = 0)
FEATURE_NAME_MAP: dict[str, str] = {
    "Air_temperature__K":      "Ambient temperature",
    "Process_temperature__K":  "Motor temperature",
    "Rotational_speed__rpm":   "Motor speed",
    "Torque__Nm":              "Load torque",
    "Tool_wear__min":          "Operating hours since service",
    "Type_L":                  "Installation type (residential)",
    "Type_M":                  "Installation type (commercial)",
}

# Dataset means (approximate, from AI4I 2020 documentation)
FEATURE_MEANS: dict[str, float] = {
    "Air_temperature__K":     300.0,
    "Process_temperature__K": 310.0,
    "Rotational_speed__rpm":  1538.8,
    "Torque__Nm":             39.99,
    "Tool_wear__min":         107.95,
    "Type_L":                 0.6,
    "Type_M":                 0.3,
}

RISK_ADJ = {"high": "High", "medium": "Moderate", "low": "Low"}


# ── Helper functions ──────────────────────────────────────────────────────────

def _days_ago(rng: random.Random, n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def _risk_level(score: float) -> str:
    if score > 0.80:
        return "high"
    if score >= 0.50:
        return "medium"
    return "low"


def _generate_trend(rng: random.Random, risk_score: float, level: str) -> list[float]:
    trend: list[float] = []
    if level == "high":
        start = max(0.3, risk_score - rng.uniform(0.3, 0.5))
        for i in range(6):
            val = start + (risk_score - start) * (i / 5) + rng.uniform(-0.03, 0.03)
            trend.append(round(min(0.99, max(0.0, val)), 2))
    elif level == "medium":
        start = max(0.2, risk_score - rng.uniform(0.1, 0.2))
        for i in range(6):
            val = start + (risk_score - start) * (i / 5) + rng.uniform(-0.04, 0.04)
            trend.append(round(min(0.79, max(0.0, val)), 2))
    else:
        base = risk_score
        for _ in range(6):
            val = base + rng.uniform(-0.05, 0.05)
            trend.append(round(min(0.49, max(0.0, val)), 2))
    trend[-1] = round(risk_score, 2)
    return trend


def _format_value(col: str, raw: float, shap_val: float) -> str:
    mean = FEATURE_MEANS.get(col, 0.0)
    delta = raw - mean
    direction = shap_val > 0  # True = pushes toward failure

    if col == "Air_temperature__K":
        sign = "+" if delta >= 0 else "−"
        qualifier = "above avg" if direction else "within range"
        return f"{raw:.0f} K ({sign}{abs(delta):.1f} K, {qualifier})"
    if col == "Process_temperature__K":
        sign = "+" if delta >= 0 else "−"
        qualifier = "above avg" if direction else "within range"
        return f"{raw:.0f} K ({sign}{abs(delta):.1f} K, {qualifier})"
    if col == "Rotational_speed__rpm":
        qualifier = "high RPM" if direction else "normal"
        return f"{raw:.0f} rpm ({qualifier})"
    if col == "Torque__Nm":
        sign = "+" if delta >= 0 else "−"
        qualifier = "above avg" if direction else "within range"
        return f"{raw:.1f} Nm ({sign}{abs(delta):.1f} Nm, {qualifier})"
    if col == "Tool_wear__min":
        hrs = raw / 60
        qualifier = "high" if direction else "recent"
        return f"{hrs:.0f} hrs ({qualifier})"
    if col in ("Type_L", "Type_M"):
        return "yes" if raw > 0.5 else "no"
    return f"{raw:.2f}"


def _synthesise_features(
    rng: random.Random,
    building_type: str,
    floor_count: int,
    hourly_trips_avg: int,
    days_since_service: int,
    push_to_failure: bool = False,
) -> dict[str, float]:
    """Synthesise one feature vector in AI4I feature space."""
    # Air temperature
    base_air = 300.0 + (2.0 if building_type == "infrastructure" else 0.0)
    air_temp = rng.gauss(base_air, 2.0)
    if push_to_failure:
        air_temp = rng.gauss(304.0, 1.0)

    # Process temperature
    proc_temp = air_temp + rng.gauss(10.0, 1.0)
    if push_to_failure:
        proc_temp = air_temp + rng.gauss(14.0, 0.5)

    # Torque — higher for taller buildings and heavy-use
    torque_base = 40.0 + floor_count * 0.3
    torque = rng.gauss(torque_base, 10.0)
    torque = max(3.0, min(80.0, torque))
    if push_to_failure:
        torque = rng.gauss(65.0, 5.0)

    # Rotational speed — derived from power ~2860W
    power = 2860.0
    rpm = (power / max(torque, 1.0)) * 9.549 + rng.gauss(0, 50)
    rpm = max(1168.0, min(2860.0, rpm))

    # Tool wear — proxy for operating hours since last service
    trip_duration_min = 1.5
    tool_wear = days_since_service * hourly_trips_avg * trip_duration_min
    tool_wear = max(0.0, min(253.0, tool_wear))
    if push_to_failure:
        tool_wear = rng.gauss(220.0, 15.0)
        tool_wear = max(180.0, min(253.0, tool_wear))

    # Type one-hot: drop_first on sorted H/L/M drops H (infrastructure = reference)
    # Type_L=1 for residential, Type_M=1 for commercial/office, both=0 for infrastructure
    type_l = 1.0 if building_type == "residential" else 0.0
    type_m = 1.0 if building_type in ("commercial", "office") else 0.0

    return {
        "Air_temperature__K":     round(air_temp, 2),
        "Process_temperature__K": round(proc_temp, 2),
        "Rotational_speed__rpm":  round(rpm, 2),
        "Torque__Nm":             round(torque, 2),
        "Tool_wear__min":         round(tool_wear, 2),
        "Type_L":                 type_l,
        "Type_M":                 type_m,
    }


# ── Build fleet metadata ──────────────────────────────────────────────────────

def _build_fleet_meta(rng: random.Random) -> list[dict]:
    """Reproduce the same elevator metadata as seed.py _build_elevators()."""
    fleet = []

    # 3 high-risk candidates (indices 0-2) — same model picks as seed.py
    for i in range(3):
        model_name, brand, model_year = ELEVATOR_MODELS[rng.randint(0, 8)]
        age = 2026 - model_year
        btype = rng.choices(BUILDING_TYPES, BUILDING_TYPE_WEIGHTS)[0]
        trips = rng.randint(18, 45)
        days_svc = rng.randint(140, 210)
        fleet.append({
            "id": f"ELV-{i + 1:03d}",
            "building_name": BUILDING_NAMES[i],
            "building_type": btype,
            "floor_count": rng.randint(4, 28),
            "model": model_name,
            "brand": brand,
            "age_years": age,
            "in_model_scope": True,
            "hourly_trips_avg": trips,
            "days_since_service": days_svc,
            "last_visit_date": _days_ago(rng, days_svc),
            "last_visit_technician": rng.choice(TECHNICIANS),
            "last_visit_notes": "Routine preventive maintenance completed. No anomalies recorded.",
            "zone": "Madrid",
        })

    # 12 medium-risk candidates (indices 3-14)
    for i in range(12):
        idx = 3 + i
        model_name, brand, model_year = ELEVATOR_MODELS[rng.randint(0, 10)]
        age = 2026 - model_year
        btype = rng.choices(BUILDING_TYPES, BUILDING_TYPE_WEIGHTS)[0]
        in_scope = brand == "own" or age <= 10
        trips = rng.randint(8, 35)
        days_svc = rng.randint(90, 145)
        fleet.append({
            "id": f"ELV-{idx + 1:03d}",
            "building_name": BUILDING_NAMES[idx],
            "building_type": btype,
            "floor_count": rng.randint(3, 20),
            "model": model_name,
            "brand": brand,
            "age_years": age,
            "in_model_scope": in_scope,
            "hourly_trips_avg": trips,
            "days_since_service": days_svc,
            "last_visit_date": _days_ago(rng, days_svc),
            "last_visit_technician": rng.choice(TECHNICIANS),
            "last_visit_notes": "Preventive visit completed. Minor door adjustment performed.",
            "zone": rng.choice(["Madrid", "Barcelona", "Sevilla", "Bilbao", "Valencia"]),
        })

    # 85 low-risk (indices 15-99)
    for i in range(85):
        idx = 15 + i
        model_name, brand, model_year = ELEVATOR_MODELS[rng.randint(0, 11)]
        age = 2026 - model_year
        btype = rng.choices(BUILDING_TYPES, BUILDING_TYPE_WEIGHTS)[0]
        in_scope = brand == "own" or age <= 12
        trips = rng.randint(4, 25)
        days_svc = rng.randint(5, 89)
        fleet.append({
            "id": f"ELV-{idx + 1:03d}",
            "building_name": BUILDING_NAMES[idx % len(BUILDING_NAMES)],
            "building_type": btype,
            "floor_count": rng.randint(2, 15),
            "model": model_name,
            "brand": brand,
            "age_years": age,
            "in_model_scope": in_scope,
            "hourly_trips_avg": trips,
            "days_since_service": days_svc,
            "last_visit_date": _days_ago(rng, days_svc),
            "last_visit_technician": rng.choice(TECHNICIANS),
            "last_visit_notes": "Routine preventive maintenance. All systems nominal.",
            "zone": ZONES[i % len(ZONES)],
        })

    return fleet


# ── SHAP explainability ───────────────────────────────────────────────────────

def _shap_features(
    col_names: list[str],
    feature_vec: dict[str, float],
    shap_vals: np.ndarray,
) -> list[dict]:
    """Return top-3 features by |SHAP|, normalised to sum=1.0."""
    raw_arr = np.array([feature_vec[c] for c in col_names])
    top3_idx = np.argsort(np.abs(shap_vals))[-3:][::-1]
    top3_abs = np.abs(shap_vals[top3_idx])
    impacts = top3_abs / top3_abs.sum()

    return [
        {
            "name": FEATURE_NAME_MAP.get(col_names[j], col_names[j]),
            "impact": round(float(impacts[k]), 3),
            "value": _format_value(col_names[j], float(raw_arr[j]), float(shap_vals[j])),
        }
        for k, j in enumerate(top3_idx)
    ]


def _nl_explanation(risk_level: str, features: list[dict]) -> str:
    f = features
    return (
        f"{RISK_ADJ[risk_level]} risk: {f[0]['name']} ({f[0]['value']}) is the primary "
        f"driver, combined with {f[1]['name']} ({f[1]['value']}) and "
        f"{f[2]['name']} ({f[2]['value']})."
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def generate(model_path: pathlib.Path = MODEL_PATH) -> None:
    if not model_path.exists():
        print(f"ERROR: model not found at {model_path}", file=sys.stderr)
        print("Run backend/ml/train.py first.", file=sys.stderr)
        sys.exit(1)

    print(f"Loading model from {model_path} …")
    model = joblib.load(model_path)
    col_names: list[str] = model.get_booster().feature_names

    print("Building fleet metadata …")
    fleet_meta = _build_fleet_meta(random.Random(42))  # separate RNG for meta
    in_scope = [e for e in fleet_meta if e["in_model_scope"]]
    out_scope = [e for e in fleet_meta if not e["in_model_scope"]]

    print(f"  {len(fleet_meta)} elevators · {len(in_scope)} in-scope · {len(out_scope)} out-of-scope")

    # ── Synthesise feature matrix for in-scope elevators ─────────────────────
    feat_rng = random.Random(42)
    feature_vecs: list[dict[str, float]] = []
    for e in in_scope:
        fv = _synthesise_features(
            feat_rng,
            building_type=e["building_type"],
            floor_count=e["floor_count"],
            hourly_trips_avg=e["hourly_trips_avg"],
            days_since_service=e["days_since_service"],
        )
        feature_vecs.append(fv)

    X = np.array([[fv[c] for c in col_names] for fv in feature_vecs])

    # ── Predict ───────────────────────────────────────────────────────────────
    risk_scores = model.predict_proba(X)[:, 1].tolist()

    # High-risk guarantee: at least 1 elevator with score > 0.80
    max_attempts = 20
    attempt = 0
    while max(risk_scores) < 0.80 and attempt < max_attempts:
        attempt += 1
        print(f"  High-risk guarantee: re-sampling (attempt {attempt}) …")
        # Re-sample the 3 candidates most likely to fail (oldest × busiest)
        candidates = sorted(
            range(len(in_scope)),
            key=lambda i: in_scope[i]["age_years"] * in_scope[i]["hourly_trips_avg"],
            reverse=True,
        )[:3]
        for ci in candidates:
            fv = _synthesise_features(
                random.Random(42 + attempt),
                building_type=in_scope[ci]["building_type"],
                floor_count=in_scope[ci]["floor_count"],
                hourly_trips_avg=in_scope[ci]["hourly_trips_avg"],
                days_since_service=in_scope[ci]["days_since_service"],
                push_to_failure=True,
            )
            feature_vecs[ci] = fv
            X[ci] = [fv[c] for c in col_names]
        risk_scores = model.predict_proba(X)[:, 1].tolist()

    high_count = sum(1 for s in risk_scores if s > 0.80)
    print(f"  Predictions complete · max score={max(risk_scores):.3f} · {high_count} high-risk")

    # ── SHAP ──────────────────────────────────────────────────────────────────
    print("Computing SHAP values …")
    explainer = shap.TreeExplainer(model)
    shap_matrix = explainer.shap_values(X)  # shape: (n, n_features)

    # ── Assemble in-scope predictions ─────────────────────────────────────────
    pred_rng = random.Random(42)
    in_scope_preds: list[dict] = []
    for i, e in enumerate(in_scope):
        score = round(risk_scores[i], 4)
        level = _risk_level(score)
        feats = _shap_features(col_names, feature_vecs[i], shap_matrix[i])
        nl = _nl_explanation(level, feats)
        trend = _generate_trend(pred_rng, score, level)
        in_scope_preds.append({
            **e,
            "risk_score": score,
            "risk_level": level,
            "nl_explanation": nl,
            "features": feats,
            "trend": trend,
        })

    # ── Assemble out-of-scope predictions ─────────────────────────────────────
    out_rng = random.Random(42)
    out_scope_preds: list[dict] = []
    for e in out_scope:
        score = round(out_rng.uniform(0.03, 0.25), 4)  # low, model-free placeholder
        out_scope_preds.append({
            **e,
            "risk_score": None,
            "risk_level": None,
            "nl_explanation": "",
            "features": [],
            "trend": [0.0] * 6,
        })

    # ── Merge and sort by id ──────────────────────────────────────────────────
    all_preds = in_scope_preds + out_scope_preds
    all_preds.sort(key=lambda e: e["id"])

    assert len(all_preds) == 100, f"Expected 100 elevators, got {len(all_preds)}"

    OUTPUT_PATH.write_text(json.dumps(all_preds, indent=2, ensure_ascii=False))
    print(f"\nWrote {len(all_preds)} predictions to {OUTPUT_PATH}")

    # Quick validation
    in_scope_entries = [p for p in all_preds if p["risk_score"] is not None]
    for p in in_scope_entries:
        total_impact = sum(f["impact"] for f in p["features"])
        assert 0.99 <= total_impact <= 1.01, f"{p['id']}: impacts sum={total_impact}"
        assert p["nl_explanation"], f"{p['id']}: empty nl_explanation"
        assert len(p["trend"]) == 6, f"{p['id']}: trend length {len(p['trend'])}"
    assert any(p["risk_score"] > 0.80 for p in in_scope_entries), "No high-risk elevator found"
    print("Validation passed ✓")


if __name__ == "__main__":
    generate()
