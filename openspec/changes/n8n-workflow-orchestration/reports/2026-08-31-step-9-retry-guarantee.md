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

---

# Addendum — Step 8, and three more generator defects the canary caught

## The digest workflow

`Schedule (06:00 Europe/Madrid) + Manual Trigger → POST /api/inference/run →
GET /api/elevators → Code (facts) → AI Agent (prose)`. Both triggers feed the
same chain, so a demonstration never waits for 06:00.

The Code node computes every number — the level counts, the top five by score,
the run's own skip counts — and the agent is told to use only what it is given.
Output from a real run:

> Today's fleet risk distribution shows 69 lifts at low risk, one at medium
> risk, and none at high risk. The lift in the Oficinas Castellana building in
> Valencia, with a medium risk score of 0.7445, needs immediate attention […]
> No lifts were skipped during today's run […] 30 lifts were out of scope.

Every figure in that paragraph is checkable against the database. The model
contributed the wording and nothing else.

Trend length stayed at exactly 6 points per lift across the re-scoring.

## The Kelvin canary earned its place three more times

Acceptance criterion 17.5 — *fleet score variance > 0* — is the only check that
looks at whether the generated data means anything. It failed three separate
times after the first fix, each with a different cause, and each would have
shipped a demonstration of seventy identical healthy lifts.

**1. The scenario moved the whole fleet, and the window average cancelled it.**
The first generator folded the scenario into a single hash, so every lift was
re-rolled from scratch each tick, and `load_factor` multiplied the whole fleet's
torque at once. Both effects are global, and the inference run averages a
24-hour window. Measured directly:

| ticks averaged | before | after |
|---|---|---|
| 1 | sd 6.69 | sd 9.23 |
| 4 | sd 3.04 | sd 9.24 |
| 16 | sd 3.04 | sd 9.24 |
| 96 | sd 3.04 | sd 9.24 |

Fixed by splitting the lift's persistent operating character (scenario-independent,
σ 12) from a light per-tick jitter. Confirmed against the live stack: per-tick
sd 9.10 and 9.29, window-average sd **9.12**.

**2. It fabricated `motor_run_hours_cumulative`.** The real formula needs
`hourly_trips_avg`, which is not in the `GET /api/elevators` response — this
producer cannot compute it. The column is nullable for exactly that reason: the
inference service falls back to the lift's own building type, usage and age,
using the same function the offline script uses. The generator was inventing a
duty factor of 0.06 and overriding a correct fallback with a worse guess.
Consumed motor life is the strongest discriminator in this model, so a
fabricated constant gave every lift the same wear curve. Removing the field
moved variance from `0.000000` to `0.000065`.

**3. The deterministic gaussian had no tails.** Sum-of-three-uniforms has the
right mean and σ and is *bounded*: it can never land further than 1.5σ from the
mean. That is fatal here, because the high-risk signature in this model is **low
torque with exhausted motor life** — the committed `predictions.json` has ELV-001
at **9.5 Nm scoring 0.7999**, and 9.5 is a −3σ draw from a mean of 40. The
truncated distribution never reached it, so the fleet came out uniformly healthy
while looking statistically reasonable. Replaced with Box–Muller.

| | after fix 1 | after fix 2 | after fix 3 |
|---|---|---|---|
| torque range | 22.7..60.6 | 22.7..60.6 | **16.1..64.6** |
| variance | 0.000000 | 0.000065 | **0.008638** |
| distinct scores | 12 | 14 | **16** |
| score range | 0.0000..0.0027 | 0.0000..0.0580 | **0.0000..0.7445** |

The fleet still reads mostly healthy, which is a defensible thing for a
well-maintained fleet on an ordinary day, and the scores now differentiate.
Whether to bias the generator toward more units in trouble is a demonstration
choice, not a correctness one, and is left alone.

## A defect found by using the scripts, not by reading them

Re-importing a **published** workflow into the live instance broke it with
`Credentials not found`: the export deliberately strips credential blocks. The
import succeeded and the execution failed, which is exactly what the spec
scenario describes — but it left the round trip broken for anyone following the
README. `scripts/n8n-import-workflow.sh` closes it, mapping node types back onto
the credential ids the bootstrap script creates.

Also fixed while running things: a `ReferenceError: seed is not defined`, from a
patch that removed the line defining it along with the block it was replacing.
Three consecutive scheduled executions failed on it before it was noticed —
which is an argument for watching the execution list, not the file.

## Outcome

**PASS** — step 8 complete, both workflows active and exported.
