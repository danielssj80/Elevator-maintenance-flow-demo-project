from datetime import date, timedelta
import random

random.seed(42)

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
    "Residencial Teatinos", "Centro Comercial Málaga"
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
    "Roberto Díaz", "Isabel Pérez"
]

NL_EXPLANATIONS = {
    "high": [
        "Elevated risk due to abnormal vibration (2.4× baseline over 72 hours) and approaching 6-month service interval.",
        "Critical risk detected: motor current fluctuations outside normal range for 5 consecutive days, combined with worn door seal indicators.",
        "High failure probability driven by temperature anomaly in drive unit (+18°C above baseline) and overdue lubrication cycle.",
        "Elevated risk: door cycle count has exceeded threshold between services, with increasing open/close error rate over the past 4 days.",
    ],
    "medium": [
        "Moderate risk: vibration levels trending upward over the past week, approaching warning threshold. Scheduled visit recommended.",
        "Increased wear indicators on door mechanism. Current levels within range but trajectory suggests intervention before next scheduled visit.",
        "Motor current shows minor deviations from baseline. Not critical, but pattern warrants monitoring before next scheduled service.",
        "Slight temperature anomaly detected. Combined with time since last visit, risk is elevated above baseline.",
    ],
    "low": [
        "Operating within normal parameters. No anomalies detected in recent telemetry.",
        "All sensors within expected range. Last visit completed successfully with no observations.",
        "Normal operation. Vibration, temperature, and door cycle metrics all within baseline.",
        "System healthy. Telemetry consistent with post-service baseline.",
    ],
}

FEATURE_SETS = {
    "high": [
        [{"name": "Vibration anomaly", "impact": 0.45, "value": "2.4× baseline"}, {"name": "Days since last service", "impact": 0.31, "value": "168 days"}, {"name": "Door error rate", "impact": 0.24, "value": "+340% vs avg"}],
        [{"name": "Motor current deviation", "impact": 0.52, "value": "+28% above range"}, {"name": "Temperature delta", "impact": 0.29, "value": "+18°C"}, {"name": "Days since last service", "impact": 0.19, "value": "201 days"}],
        [{"name": "Door cycle overrun", "impact": 0.38, "value": "12,400 / 10,000 target"}, {"name": "Door open/close errors", "impact": 0.35, "value": "18 in 4 days"}, {"name": "Vibration trend", "impact": 0.27, "value": "+65% week-on-week"}],
    ],
    "medium": [
        [{"name": "Vibration trend", "impact": 0.41, "value": "+22% week-on-week"}, {"name": "Days since last service", "impact": 0.35, "value": "142 days"}, {"name": "Temperature delta", "impact": 0.24, "value": "+6°C"}],
        [{"name": "Door error rate", "impact": 0.44, "value": "+80% vs avg"}, {"name": "Motor current deviation", "impact": 0.32, "value": "+9% above baseline"}, {"name": "Days since last service", "impact": 0.24, "value": "118 days"}],
    ],
    "low": [
        [{"name": "Days since last service", "impact": 0.55, "value": "24 days"}, {"name": "Vibration", "impact": 0.28, "value": "Normal"}, {"name": "Temperature", "impact": 0.17, "value": "Normal"}],
        [{"name": "Vibration", "impact": 0.48, "value": "Normal"}, {"name": "Motor current", "impact": 0.33, "value": "Normal"}, {"name": "Door cycle count", "impact": 0.19, "value": "On track"}],
    ],
}


def _generate_trend(risk_score: float, level: str) -> list[float]:
    """Generate 6-day risk probability trend ending at current risk_score."""
    trend = []
    if level == "high":
        start = max(0.3, risk_score - random.uniform(0.3, 0.5))
        for i in range(6):
            val = start + (risk_score - start) * (i / 5) + random.uniform(-0.03, 0.03)
            trend.append(round(min(0.99, max(0.0, val)), 2))
    elif level == "medium":
        start = max(0.2, risk_score - random.uniform(0.1, 0.2))
        for i in range(6):
            val = start + (risk_score - start) * (i / 5) + random.uniform(-0.04, 0.04)
            trend.append(round(min(0.79, max(0.0, val)), 2))
    else:
        base = risk_score
        for _ in range(6):
            val = base + random.uniform(-0.05, 0.05)
            trend.append(round(min(0.49, max(0.0, val)), 2))
    trend[-1] = round(risk_score, 2)
    return trend


def _days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def _generate_elevators() -> list[dict]:
    elevators = []

    # 3 high-risk elevators (>80%)
    high_risk_scores = [0.91, 0.87, 0.83]
    for i, score in enumerate(high_risk_scores):
        idx = i
        model_name, brand, model_year = ELEVATOR_MODELS[random.randint(0, 8)]
        age = 2026 - model_year
        btype = random.choices(BUILDING_TYPES, BUILDING_TYPE_WEIGHTS)[0]
        nl = NL_EXPLANATIONS["high"][i % len(NL_EXPLANATIONS["high"])]
        features = FEATURE_SETS["high"][i % len(FEATURE_SETS["high"])]
        elevators.append({
            "id": f"ELV-{idx + 1:03d}",
            "building_name": BUILDING_NAMES[idx],
            "building_type": btype,
            "floor_count": random.randint(4, 28),
            "model": model_name,
            "brand": brand,
            "age_years": age,
            "risk_score": score,
            "risk_level": "high",
            "trend": _generate_trend(score, "high"),
            "last_visit_date": _days_ago(random.randint(140, 210)),
            "last_visit_technician": random.choice(TECHNICIANS),
            "last_visit_notes": "Routine preventive maintenance completed. No anomalies recorded.",
            "nl_explanation": nl,
            "features": features,
            "in_model_scope": True,
            "hourly_trips_avg": random.randint(18, 45),
            "zone": "Madrid",
        })

    # ~12 medium-risk elevators (50-80%)
    medium_count = 12
    for i in range(medium_count):
        idx = 3 + i
        score = round(random.uniform(0.51, 0.79), 2)
        model_name, brand, model_year = ELEVATOR_MODELS[random.randint(0, 10)]
        age = 2026 - model_year
        btype = random.choices(BUILDING_TYPES, BUILDING_TYPE_WEIGHTS)[0]
        nl = NL_EXPLANATIONS["medium"][i % len(NL_EXPLANATIONS["medium"])]
        features = FEATURE_SETS["medium"][i % len(FEATURE_SETS["medium"])]
        in_scope = brand == "own" or age <= 10
        elevators.append({
            "id": f"ELV-{idx + 1:03d}",
            "building_name": BUILDING_NAMES[idx],
            "building_type": btype,
            "floor_count": random.randint(3, 20),
            "model": model_name,
            "brand": brand,
            "age_years": age,
            "risk_score": score,
            "risk_level": "medium",
            "trend": _generate_trend(score, "medium"),
            "last_visit_date": _days_ago(random.randint(90, 145)),
            "last_visit_technician": random.choice(TECHNICIANS),
            "last_visit_notes": "Preventive visit completed. Minor door adjustment performed.",
            "nl_explanation": nl,
            "features": features,
            "in_model_scope": in_scope,
            "hourly_trips_avg": random.randint(8, 35),
            "zone": random.choice(["Madrid", "Barcelona", "Sevilla", "Bilbao", "Valencia"]),
        })

    # Remaining 85 as low-risk (<50%)
    zones = ["Madrid", "Barcelona", "Sevilla", "Bilbao", "Valencia", "Zaragoza", "A Coruña", "Santander", "Málaga"]
    for i in range(85):
        idx = 15 + i
        score = round(random.uniform(0.03, 0.49), 2)
        level = "low"
        model_name, brand, model_year = ELEVATOR_MODELS[random.randint(0, 11)]
        age = 2026 - model_year
        btype = random.choices(BUILDING_TYPES, BUILDING_TYPE_WEIGHTS)[0]
        nl = NL_EXPLANATIONS["low"][i % len(NL_EXPLANATIONS["low"])]
        features = FEATURE_SETS["low"][i % len(FEATURE_SETS["low"])]
        in_scope = brand == "own" or age <= 12
        elevators.append({
            "id": f"ELV-{idx + 1:03d}",
            "building_name": BUILDING_NAMES[idx % len(BUILDING_NAMES)],
            "building_type": btype,
            "floor_count": random.randint(2, 15),
            "model": model_name,
            "brand": brand,
            "age_years": age,
            "risk_score": score,
            "risk_level": level,
            "trend": _generate_trend(score, level),
            "last_visit_date": _days_ago(random.randint(5, 89)),
            "last_visit_technician": random.choice(TECHNICIANS),
            "last_visit_notes": "Routine preventive maintenance. All systems nominal.",
            "nl_explanation": nl,
            "features": features,
            "in_model_scope": in_scope,
            "hourly_trips_avg": random.randint(4, 25),
            "zone": zones[i % len(zones)],
        })

    return sorted(elevators, key=lambda e: e["risk_score"], reverse=True)


ELEVATORS: list[dict] = _generate_elevators()
ELEVATOR_INDEX: dict[str, dict] = {e["id"]: e for e in ELEVATORS}
