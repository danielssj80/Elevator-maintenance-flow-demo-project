# Design: feature-direction

## Direction value

A string enum on each feature:

- `"increases"` — SHAP value > 0, the factor pushes the risk score **up** (toward failure).
- `"decreases"` — SHAP value ≤ 0, the factor pushes the risk score **down** (protective).

Ties (`shap == 0`, effectively never for top-3) fall to `"decreases"` (no upward push).
`impact` stays as the normalised `|SHAP|` magnitude — `direction` only adds the sign that
was previously discarded.

## Generation (`generate_predictions.py`)

`_shap_features` already has `shap_vals[j]`. Add one field:

```python
return [
    {
        "name": FEATURE_NAME_MAP.get(col_names[j], col_names[j]),
        "impact": round(float(impacts[k]), 3),
        "value": _format_value(col_names[j], float(raw_arr[j]), float(shap_vals[j])),
        "direction": "increases" if shap_vals[j] > 0 else "decreases",
    }
    for k, j in enumerate(top3_idx)
]
```

## Persistence

- **ORM** (`models/elevator.py`): `ElevatorFeature.direction: Mapped[str]`.
- **Schema** (`schemas/elevator.py`): `FeatureSchema.direction: str`.
- **seed.py**: pass `direction=f["direction"]` when building `ElevatorFeature`.
- **Migration** (schema + data): `op.add_column("elevator_features", Column("direction",
  String, nullable=False, server_default="increases"))`, then repopulate feature rows from
  `predictions.json` (delete + reinsert per elevator PK, same in-place pattern as
  `2c43876e02dd`, so `visit_reports` is untouched). The `server_default` covers the brief
  window between add-column and reinsert; every row is then overwritten with its real
  direction.

## API (`docs/api-spec.yml`)

Add to the `Feature` schema (additive, `required`):

```yaml
direction:
  type: string
  enum: [increases, decreases]
  description: Whether the factor pushes the risk score up (increases) or down (decreases)
  example: increases
```

## Frontend (`FeatureBar.tsx`, `types/elevator.ts`)

`Feature` type gains `direction: 'increases' | 'decreases'`.

Render an arrow + colour next to the factor name; tint the weight bar to match:

- `increases` → ↑, red (`text-red-*` / `bg-red-*`) — raises risk.
- `decreases` → ↓, green (`text-green-*` / `bg-green-*`) — lowers risk.

Keep the "% of prediction weight" caption (magnitude is still meaningful); the arrow/colour
disambiguates whether that weight is pushing risk up or down. So ELV-073's "Motor useful
life remaining 97% remaining" shows a green ↓ (protective) rather than looking like a driver.

## ADR: string enum vs signed impact

**Decision:** add a separate `direction` string rather than making `impact` signed
(e.g. −0.14).

**Rationale:** `impact` is a 0–1 proportion that sums to ~1.0 across the three features and
is consumed as a bar width; making it negative would break that contract and every existing
consumer. A separate enum is additive, self-documenting in the API, and trivial to render.

## Out of scope

- Changing `impact` semantics or the top-3 selection.
- Retraining the model.
- Reworking the voice briefing (already handles direction via the LLM).
