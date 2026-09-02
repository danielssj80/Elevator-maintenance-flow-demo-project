# Step 14 Report — Manual Endpoint Testing

- **Date**: 2026-09-01
- **Change**: n8n-workflow-orchestration

Executed by the agent against the running stack. This step was open when the
independent review ran and is closed here.

## Images rebuilt first

```bash
docker compose build backend migrate
docker compose up -d --force-recreate backend
```

Both, not just `backend`: `migrate` builds its own image from the same
Dockerfile and is what applies Alembic, so rebuilding one and not the other
leaves a stack that exits successfully having applied nothing.

## Endpoints

| Request | Expected | Observed |
|---|---|---|
| `POST /api/telemetry/readings`, no token | 401 | **401** |
| `POST /api/telemetry/readings`, wrong token | 401 | **401** |
| `POST /api/telemetry/readings`, valid token | 201 | **201** |
| the same batch again | `accepted 0` | **`accepted=0 duplicates_ignored=1`** |
| invalid body, valid token | 422 | **422** |
| `POST /api/inference/run`, no token | 401 | **401** |
| `POST /api/inference/run`, valid token | 200 | **200** |
| `GET /api/telemetry/readings` (unguarded by design) | 200 | **200** |
| `GET /api/elevators` | 200 | **200** |
| `GET /api/elevators/NOPE` | 404 | **404** |

## The middleware, on the freshly built image

```
$ curl -H 'X-N8N-Execution-Id: step14probe' -H 'X-N8N-Workflow-Id: wf-step14' \
    localhost:8000/api/elevators
$ tempo search '{span.n8n.execution.id="step14probe"}'
  trace bbaf9d18809a8cfe0414b93acf442e28  root GET /api/elevators
```

Queryable as a span attribute, not merely present in the code. Tempo's search
index lagged the write by some seconds — worth knowing before concluding a span
is missing.

## Step 15 — Playwright

**N/A.** Nothing under `frontend/` is touched by this change and no response
shape the dashboard reads is altered. Grafana is a separate product for a
separate audience on its own port and is deliberately not embedded in the React
app. Recorded here because step 15 asks for the determination to live in this
report.

## DB state

| Table | Pre | Post |
|---|---|---|
| `elevators` | 100 | 100 |
| `telemetry_readings` | 2660 | 2660 |

The one row this step inserted (`source='step14'`) was deleted afterwards —
`DELETE 1` — and the count returned to its starting value.

## Outcome

**PASS**
