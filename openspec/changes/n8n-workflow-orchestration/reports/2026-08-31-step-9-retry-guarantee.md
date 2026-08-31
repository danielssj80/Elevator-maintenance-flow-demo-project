# Step 7/9 Report — The Ingest Workflow and the Retry Guarantee

- **Date**: 2026-08-31
- **Change**: n8n-workflow-orchestration

## The workflow runs

`Schedule (15 min) → AI Agent (Bedrock Nova Lite + Structured Output Parser) →
GET /api/elevators → Code → POST /api/telemetry/readings`, activated, execution
status `success`.

The agent genuinely ran — it is not falling back. Its output, read from
`execution_data`, was `ambient_c_base: 28`, `load_factor: 1`, and the ingested
ambient temperatures centre on 28 rather than on the fallback's 24.

70 readings for the 70 in-scope lifts, and `min(recorded_at) = max(recorded_at)`
for the batch, which is the property the retry guarantee rests on.

## The retry guarantee, end to end

The exact batch the workflow submitted was reconstructed from the database and
re-posted — which is precisely what n8n sends when it retries a failed node.

```
filas antes: 140
accepted=0  duplicates_ignored=140  rejected=[]
filas después: 140
```

Then, the part that actually matters — that a retry does not move a score:

```
inference 1 : scored=70 readings=140
retry       : accepted=0 duplicates=140
inference 2 : scored=70 readings=140
→ 100 risk scores identical, byte for byte
→ trend still exactly 6 points per lift
```

This is what `harden-telemetry-ingest` was carved out of this change for, now
demonstrated against a real workflow payload rather than a hand-made one.

## The Kelvin canary failed first, and the cause was in this change

The milestone's acceptance criterion is *fleet score variance > 0*. The first
run of the workflow produced:

```
varianza = 0.000000    valores distintos = 2    (68 lifts at 0.0000, 2 at 0.0001)
```

That is the exact signature FIND-2 describes. It was **not** a Kelvin bug — the
inference service's plausible-Kelvin guard never fired, so the conversion was
correct. The fault was in this change's own Code node: it generated torque
across an 8 Nm band and rpm across 58, so the model was shown one operating
point wearing seventy different names.

Fixed by deriving the readings the way `_synthesise_features` in
`backend/ml/generate_predictions.py` does — the function that produced the
committed `predictions.json`:

| | before | after |
|---|---|---|
| torque range | 39.6..47.7 | 35.4..69.3 |
| variance | 0.000000 | **0.042407** |
| distinct scores | 2 | **25** |
| score range | 0.0000..0.0001 | 0.0000..0.9538 |
| risk levels | 70 low | 3 high, 1 medium, 66 low |

`motor_speed_rpm` clamps to the 1168 floor for most lifts. That is faithful to
the offline synthesis, not a defect: speed is derived from torque at constant
power, so any torque above ~23 Nm saturates the floor there too. Speed is not a
discriminating feature in this model; torque and consumed motor life are.

**Worth stating plainly**: had this shipped without the canary check, the
demonstration would have shown a flat fleet of seventy identical low-risk lifts
and looked like the model was broken.

## A dashboard panel removed for the same reason it was added

Step 6 added an "AI agent tokens and cost" panel on `n8n_instance_ai_tokens_total`.
After the agent ran successfully, those series were still `0`: they belong to
n8n's own "instance AI" feature, not to the AI Agent node. The panel was removed
rather than shipped — it is the same defect this change criticised change 1 for,
a query that can never return data.

## Export hygiene (step 10)

`scripts/export-n8n-workflow.sh` strips credential blocks, `meta.instanceId`,
`versionId` and pinned data, forces `active: false`, and refuses to write a file
that still mentions any of them. Verified:

- The scrubbed export contains no `credentials` and no `instanceId`.
- It **still imports** into a clean n8n instance on a fresh database, with all
  7 nodes intact.

`id` is kept deliberately: n8n's importer fails on a NOT NULL constraint without
one, and these ids are fixed literals chosen for this repository.

Two bugs were found by running the scripts rather than reading them: the
credential bootstrap assigned the ingest token without exporting it, so the
python subprocess only saw it in a shell that already had it; and the export
script used two heredocs, of which bash keeps only the last, so python received
the workflow JSON as its own source.

## Outcome

**PASS** — steps 7, 9, 10.1–10.3 and 10.5 complete. 10.4 (canvas screenshots) is
open and needs the editor UI.
