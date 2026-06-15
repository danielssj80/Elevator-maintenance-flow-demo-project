# Step 11 — Manual Endpoint Testing Report

**Date:** 2026-06-15
**Change:** pre-visit-voice-briefing

## Test Environment

- Docker container (no AWS creds): `http://localhost:8000`
- Local uvicorn with AWS creds: `http://localhost:8001`

## Results

### 11.2 — Bedrock path (local uvicorn with AWS creds)

```
GET /api/elevators/ELV-001/briefing → 200
{
  "elevator_id": "ELV-001",
  "text": "We've got ELV-001 at Torre Picasso, a high-risk unit with a score of 0.91. ...",
  "source": "bedrock",
  "generated_at": "2026-06-15T10:18:32.213998Z"
}
```
✓ Non-empty text, source="bedrock", elevator_id correct.

### 11.3 — Unknown elevator (404)

```
GET /api/elevators/UNKNOWN/briefing → 404
{"detail": "Elevator not found"}
```
✓ Correct 404 response.

### 11.4 — Fallback path (Docker container, no AWS credentials)

```
GET /api/elevators/ELV-001/briefing → 200
{
  "source": "fallback",
  "text": "Unit ELV-001 at Torre Picasso is at high risk (score 0.91). ..."
}
```
✓ source="fallback", 200 OK (no 5xx), coherent briefing.

### 11.5 — DB state

No DB mutation (read-only endpoint). Confirmed — no rows added to any table.

## Bedrock Verification

Direct boto3 call to `eu.amazon.nova-lite-v1:0` in `eu-north-1` succeeded independently. Model responds correctly via the Converse API.
