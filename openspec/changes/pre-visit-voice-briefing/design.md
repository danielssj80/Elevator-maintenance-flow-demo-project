# Design: pre-visit-voice-briefing

## Context

The unit detail view (`GET /api/elevators/{id}`) already returns everything the briefing needs: `risk_score`/`risk_level`, three `features` (name/impact/value), the 6-day `trend`, `last_visit_date`/`last_visit_technician`/`last_visit_notes`, `nl_explanation`, and `in_model_scope`. This change adds a read-only capability that turns that data into a spoken briefing. It touches the backend three-layer architecture (a new router route → service → Bedrock client) and the frontend service-layer + component pattern. No persistence, no schema changes.

Production runs on a single `t3.micro` EC2 instance in `eu-north-1` behind nginx/TLS. Amazon Bedrock is reachable from `eu-north-1` via EU cross-region inference profiles; `eu.amazon.nova-lite-v1:0` was verified ACTIVE and invokable via the Converse API with the `daniel-admin` IAM user.

## Goals / Non-Goals

**Goals:**
- A `GET /api/elevators/{id}/briefing` endpoint returning a grounded, natural-language briefing (~4–8 sentences) for a unit.
- LLM generation via Bedrock Converse, model/region configurable by env var; swapping to Claude Haiku 4.5 requires no code change.
- A deterministic fallback so a valid unit never yields 5xx on model failure.
- Browser playback via the Web Speech API with a text-only fallback.

**Non-Goals:**
- Post-visit voice input / Whisper / report pre-fill (M4b).
- Server-side TTS or audio files.
- Persisting briefings; analytics; multi-language; refactoring the existing direct-`fetch` calls in `ElevatorDetail.tsx`.

## Decisions

### D1 — Bedrock Converse API behind a thin client (`bedrock_client.py`)
A `bedrock_client.py` in `services/` wraps `boto3` `bedrock-runtime.converse`, taking a system prompt + user message and returning the assistant text. Using **Converse** (not `invoke_model`) keeps request/response shape identical across model families, so changing `BEDROCK_MODEL_ID` is the only step to switch models. The boto3 client is configured with short connect/read timeouts (~5 s) and minimal retries so failures fall back fast.

### D2 — Orchestration in `briefing_service.py`
`BriefingService` fetches the elevator (404 via `HTTPException` if missing, matching `ElevatorService`), builds the prompt from the unit's fields, calls the Bedrock client, and on any exception/timeout returns the deterministic fallback. It reuses the existing `_derive_risk_level` logic. Returns a `BriefingSchema { elevator_id, text, source, generated_at }`.

### D3 — Prompt design grounded in unit data
The system prompt instructs: a concise spoken briefing of ~4–8 sentences, plain language for a technician about to visit, grounded **only** in the supplied facts (no invented numbers), ending with one or two concrete recommendations. The user message carries structured facts: risk level/score, the three drivers with values, trend direction (rising/stable/falling from the 6-day array), days since `last_visit_date`, and `nl_explanation` as supporting context. For `in_model_scope == false`, the prompt instructs the model to state that no model prediction exists and to refer to last-visit notes. `maxTokens` ~450, `temperature` low (~0.3) for consistency.

### D4 — Deterministic fallback builder
A pure function assembles a briefing from the same facts using templates (e.g. "Unit ELV-001 in <building> is at <level> risk (<score>). Main drivers: <f1>, <f2>. Risk is <trend>. Last visited <N> days ago. Recommend …"). It is also the substrate the unit tests assert on without calling Bedrock, and is returned with `source: "fallback"`.

### D5 — Config via `os.getenv` (matches `core/config.py` style)
Add to `Settings`: `bedrock_region` (`BEDROCK_REGION`, default `eu-north-1`), `bedrock_model_id` (`BEDROCK_MODEL_ID`, default `eu.amazon.nova-lite-v1:0`), and `briefing_timeout_seconds` (default 5). No credentials in code — boto3 resolves the IAM role/identity from the environment.

### D6 — Optional in-memory cache
A process-local dict keyed by `(elevator_id, risk_score)` caches the generated text so repeated "Brief me" clicks in a demo don't re-invoke the model. Trivial and bounded by fleet size; invalidates implicitly when `risk_score` changes. Kept optional and simple (no TTL eviction needed at this scale).

### D7 — Frontend service layer + component
Per `frontend-standards.md`, a new `src/services/briefingService.ts` exposes `getBriefing(id): Promise<Briefing>`; the component never calls `fetch` directly. A `VoiceBriefing.tsx` component manages states (idle → loading → ready/speaking) and uses `window.speechSynthesis` + `SpeechSynthesisUtterance`, feature-detecting support and providing Play/Stop. It is mounted in `ElevatorDetail.tsx` for `in_model_scope` units, with a subtle marker when `source === "fallback"`. `data-testid` attributes are added for the Playwright E2E.

## Risks / Trade-offs

- [Bedrock latency/availability] → ~5 s timeout + deterministic fallback; endpoint stays 2xx for valid units.
- [Web Speech API voice quality varies by browser/OS] → acceptable for a demo; text is always shown so audio is an enhancement, not the only channel.
- [Instance role lacks `bedrock:InvokeModel`] → covered by a deploy step; until granted, production returns the fallback (degraded but not broken).
- [Model output drifts from facts] → low temperature + prompt grounded only in supplied facts; fallback is fully deterministic.

## Migration Plan

1. Implement and test locally against Bedrock with the `daniel-admin` identity.
2. Add `boto3` to backend requirements and the Bedrock env vars to `docker-compose.prod.yml`.
3. Grant the production EC2 instance role `bedrock:InvokeModel` on the EU inference-profile ARN and routed foundation-model ARNs (one-time, manual).
4. Deploy via the existing pipeline; verify on `elevator.dsaavedra.dev`.

**Rollback**: set `briefing_enabled=false` (or remove the route mount) — the rest of the app is unaffected; no data migration to reverse.

## Open Questions

- None blocking. `nl_explanation` is used as supporting context in the prompt (not copied verbatim); the in-memory cache is included as a small, optional optimisation.
