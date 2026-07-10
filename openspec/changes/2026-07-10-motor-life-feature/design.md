# Design: motor-life-feature

## The reference value: ~40,000 motor operating hours before failure

We anchor the AI4I `Tool wear` failure ceiling (253) to the **maximum run-hours an
elevator hoist motor is expected to accumulate before end-of-life failure**. Derived
from two domain facts:

| Fact | Value | Source |
|---|---|---|
| Elevator motor design/service life | ~25 years (this is what "25-year elevator life" refers to — the motor) | [ElevatorLab](https://www.elevatorlab.com/blog/how-long-does-an-elevator-last-elevator-useful-life-calculator), [Premier Elevator](https://www.premierelevatorcabs.com/optimum-elevator-life-cycles-and-maintenance/) |
| Actual motor run-time (car moving; intermittent duty, not continuous) | ~4 h/day for a busy unit | [Dazen](https://dazenelevator.com/how-much-energy-does-an-elevator-use/), [EC&M](https://www.ecmweb.com/content/article/20888237/controller-ratings-for-elevator-motors) |

```
MAX_MOTOR_HOURS ≈ 4 h/day × 365 days × 25 years ≈ 36,500 → rounded to 40,000 h
```

Cross-check: ~40,000 h matches the L10 bearing-fatigue rating of premium industrial
motors, and the motor bearing is the component that typically fails
([bearing L10 background](https://www.machinerylubrication.com/Read/29228/bearing-system-life)).

`MAX_MOTOR_HOURS = 40_000` is a single named constant in `generate_predictions.py`.

## The new synthesis rule

Replace the old `days_since_service`-based clamp with **fraction of rated motor life
consumed**, computed from the elevator's age and usage (both already in fleet metadata):

```python
MAX_MOTOR_HOURS = 40_000.0          # rated motor run-hours before failure (see above)
MOTOR_RUN_MIN_PER_TRIP = 0.4        # motor energised ~24 s per trip (door-to-door move)
ACTIVE_HOURS_PER_DAY = 16           # building active window feeding hourly_trips_avg

# cumulative lifetime motor run-hours
trips_per_day      = hourly_trips_avg * ACTIVE_HOURS_PER_DAY
run_hours_per_day  = trips_per_day * MOTOR_RUN_MIN_PER_TRIP / 60.0
life_run_hours     = run_hours_per_day * 365 * age_years

fraction_consumed  = min(1.0, life_run_hours / MAX_MOTOR_HOURS)   # 0.0 .. 1.0
tool_wear          = fraction_consumed * 253.0                    # AI4I domain
```

### Per-typology run intensity

`MOTOR_RUN_MIN_PER_TRIP` and `ACTIVE_HOURS_PER_DAY` are **per building type**, so
heavy-use buildings consume motor life faster (their risk correlates with usage,
modulated by age). Our fleet already classifies every unit by `building_type`
(residential/commercial/office/infrastructure); there is no separate "high-rise" type —
`infrastructure` (metro/airport/hospital: intense traffic, long rides) is the heavy tier.

| building_type | min/trip | active h/day | rationale |
|---|---|---|---|
| residential | 0.2 | 8 | short rides, low daytime traffic |
| commercial | 0.4 | 10 | medium rides, business-hours traffic |
| office | 0.4 | 10 | same tier as commercial |
| infrastructure | 1.5 | 16 | long rides, near-continuous heavy traffic (the "high-rise"/heavy tier) |

```python
run_min_per_trip, active_hours = RUN_PARAMS[building_type]
```

### The in-scope age cap and the aged heavy cohort

The in-scope fleet is capped at ~12 years old (the scope rule requires `brand == "own"`
or `age ≤ 10/12`, and the "own" models are from 2017–2021). Against a 25-year / 40,000-h
motor life, units that young barely dent their rated life even under heavy use — a naive
apply leaves **66/70 units at ≥ 80 % remaining and 0 in the failure band** (the opposite
over-correction from the old saturation).

To get an organic high-risk band (rather than relying on the synthetic
`push_to_failure`), the 3 high-risk-candidate slots (indices 0–2) become a deliberate
**aged, heavy-use cohort**: old **own**-brand models (so they stay in-scope) in heavy-use
buildings:

```python
OLD_HEAVY_MODELS = [
    ("ThyssenKrupp Legacy TW", "own", 2001),
    ("ThyssenKrupp Classic",   "own", 1999),
    ("ThyssenKrupp Heritage",  "own", 2004),
]
HIGH_RISK_TYPES = ["infrastructure", "commercial", "infrastructure"]
```

This yields a realistic spread (≈ 2 critical < 20 %, a few mid-band, the majority
healthy ≥ 80 %) driven by genuine age × usage, not a forced score.

## ADR: external factors (torque, temperature, speed) stay independent of age

**Decision:** only the motor-life feature is correlated with age/usage. Load torque,
motor/ambient temperature, and rotational speed remain independent random factors.

**Rationale:** if every feature scaled with age, "old ⇒ high risk" would be a rule that
needs no model. The value of the ML model is precisely that it catches a **new** unit at
risk because of an external factor (a motor built with excess torque, an intrinsically
hostile/hot environment) and clears an **old** unit whose motor is worn but whose load and
environment are nominal. These are genuinely age-independent causes, so we do **not**
artificially correlate them. Consequence, verified in the fleet: high- and medium-risk
units span all ages (6–25 yr), and the aged cohort's worn motors do not by themselves
imply high risk.

## Model is confidently bimodal → medium-risk guarantee

The trained XGBoost (`scale_pos_weight` on well-separated AI4I data) is a confident
classifier: sampling 20 000 random plausible inputs, ~87 % score at the extremes
(< 0.1 or > 0.9) and only ~4 % land in the medium band (0.50–0.80). So a purely
model-driven fleet reliably produces high-risk units but an **often-empty medium tier**
(0 of 70 in one run) — the medium risk_level and its UI path would never appear.

To keep all three tiers populated for the demo, a **medium-risk guarantee** (mirroring the
existing high-risk one) steers `MEDIUM_COUNT = 5` low-risk units into 0.50–0.80 by
**rejection-sampling only their external factors** (temperature/speed/torque), keeping each
unit's real `Tool_wear` (motor life) and `Type`. This is honest — the steered units have an
ambiguous external condition, independent of age — and reproducible (fixed
`random.Random(1234)`). Result: a stable 5 high / 5 medium / 60 low split, high and medium
both age-independent.

`push_to_failure=True` (the high-risk guarantee path) sets `fraction_consumed` directly
in the failure band, e.g. `Uniform(0.85, 0.97)` → `tool_wear ≈ 215..245`.

### Resulting distribution (fleet metadata, `random.Random(42)`)

| Unit profile | age × trips | fraction consumed | tool_wear | remaining |
|---|---|---|---|---|
| Old + heavy use | 23 yr, 40 trips/h | ~0.90 | ~227 | ~10 % |
| Typical mid | 10 yr, 20 trips/h | ~0.19 | ~49 | ~81 % |
| Young + light use | 5 yr, 5 trips/h | ~0.02 | ~6 | ~98 % |

Most of the fleet lands low-to-mid; only genuinely old, heavily-used units reach the
failure band — the opposite of today's saturation. Exact counts are produced by the
regeneration step and verified in tasks.

## Display framing: "Motor useful life remaining (%)"

Internally the model still consumes `tool_wear ∈ [0, 253]` (high = worn = failure).
For the user we **invert** it to remaining life, which is more intuitive:

```python
remaining_pct = round((1.0 - raw / 253.0) * 100)   # raw == tool_wear
# e.g. 227 -> "10% remaining", 49 -> "81% remaining", 6 -> "98% remaining"
```

- `FEATURE_NAME_MAP["Tool_wear__min"]`: `"Operating hours since service"` →
  `"Motor useful life remaining"`.
- `_format_value` branch for `Tool_wear__min`: return `f"{remaining_pct}% remaining"`,
  optionally with a qualifier (`"critical"` when `remaining_pct < 20`). No longer uses
  `FEATURE_MEANS` for this column.

`nl_explanation` uses the same `feature.value` string, so it reads e.g. *"…Motor useful
life remaining (10% remaining) is the primary driver…"* with no template change needed.
(Copy tidy-up of the doubled word is a nice-to-have, tracked in tasks.)

## Why the model does not need retraining

`train.py` trains on the **real** AI4I dataset (real `Tool wear` values); that is
unchanged. We only change how we synthesise the 100 elevator feature vectors we feed to
the already-trained model at prediction time. So `model.joblib` is byte-for-byte the
same; only `predictions.json` regenerates.

## Production resync (migration)

Same rationale and pattern as migration `0aac4958720e`: update each existing `elevators`
row **in place by primary key** and fully replace its `elevator_features` /
`elevator_trend_points`, rather than delete+reseed — because `visit_reports` has an
`ON DELETE CASCADE` FK to `elevators.id` and the public report form is live. The new
migration reads the regenerated `predictions.json` and re-applies it. Runs automatically
via the existing `migrate` compose service on every environment.

## ADR: cumulative lifetime wear vs. hours-since-service

**Decision:** model the operating-hours feature as cumulative lifetime motor wear
(age × usage), not hours since the last service.

**Rationale:** (1) It is what the user's chosen reference — "max motor hours before
failure" — naturally anchors to. (2) Motor/bearing failure is driven by total
accumulated run-hours, not by how recently a technician visited. (3) It fixes the
saturation at the root: age × usage spreads the fleet across the domain, whereas
days-since-service × trips explodes past the ceiling. `days_since_service` remains in the
metadata and still informs `last_visit_date` and the briefing; it is simply no longer the
driver of this feature.
