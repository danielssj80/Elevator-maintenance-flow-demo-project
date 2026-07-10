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

Collapsing the constants: `life_run_hours ≈ age_years × hourly_trips_avg × 38.9`
(where `38.9 = 16 × 0.4/60 × 365`). The constants `MOTOR_RUN_MIN_PER_TRIP`,
`ACTIVE_HOURS_PER_DAY`, and `MAX_MOTOR_HOURS` are the tunable knobs; their product is
chosen so a busy old unit approaches the failure region and a healthy fleet mostly sits
low-to-mid — deliberately **not** clamped-flat like before.

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
