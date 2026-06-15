# Tasks: pre-visit-voice-briefing

## 0. Setup: Create Feature Branch (MANDATORY)

- [x] 0.1 Create branch `feature/pre-visit-voice-briefing` from `main`
- [x] 0.2 Verify current branch: `git branch --show-current`

## 1. Backend: Bedrock settings

- [x] 1.1 Add `bedrock_region` (`BEDROCK_REGION`, default `eu-north-1`), `bedrock_model_id` (`BEDROCK_MODEL_ID`, default `eu.amazon.nova-lite-v1:0`), and `briefing_timeout_seconds` (default `5`) to `Settings` in `app/core/config.py` via `os.getenv`
- [x] 1.2 Add `boto3` to `backend/requirements.txt` (and dev requirements if present); install into `backend/venv`

## 2. Backend: Briefing schema

- [x] 2.1 Create `app/schemas/briefing.py` with `BriefingSchema { elevator_id: str, text: str, source: Literal["bedrock","fallback"], generated_at: datetime }` (Pydantic v2, type-hinted)

## 3. Backend: Deterministic fallback builder (TDD)

- [x] 3.1 Write failing unit test in `tests/unit/test_briefing_service.py` for the fallback builder: asserts the text references risk level, drivers, trend direction, and a recommendation, given a sample unit
- [x] 3.2 Implement the fallback builder (pure function from unit fields) reusing `_derive_risk_level`
- [x] 3.3 Add a test for an out-of-scope unit (states no prediction, points to last-visit notes); test passes

## 4. Backend: Bedrock client (TDD, mocked)

- [x] 4.1 Write failing unit test for `bedrock_client.generate(...)` with the `boto3` client mocked (asserts Converse is called with model id from settings and returns the assistant text)
- [x] 4.2 Implement `app/services/bedrock_client.py` wrapping `bedrock-runtime.converse` with short connect/read timeouts and minimal retries; test passes

## 5. Backend: Briefing service (TDD)

- [x] 5.1 Write failing test: existing in-scope unit → `source="bedrock"`, non-empty text (Bedrock client mocked to return text)
- [x] 5.2 Write failing test: Bedrock client raises/times out → `source="fallback"`, no exception propagated
- [x] 5.3 Write failing test: unknown elevator id → `HTTPException` 404
- [x] 5.4 Implement `app/services/briefing_service.py` (build prompt from unit data, call client, fall back on error); reuse `_derive_risk_level`; all tests pass
- [x] 5.5 (Optional) add process-local cache keyed by `(elevator_id, risk_score)` with a test that a second call does not re-invoke the client

## 6. Backend: Router endpoint

- [x] 6.1 Add `GET /{elevator_id}/briefing` to `app/routers/elevators.py` wiring `BriefingService` via a `Depends` factory (mirroring `get_elevator_service`)
- [x] 6.2 Endpoint returns `BriefingSchema` (200) and 404 `{"detail": "Elevator not found"}` for unknown ids

## 7. Frontend: Briefing service + types

- [x] 7.1 Add `Briefing` type to `frontend/src/types/elevator.ts`
- [x] 7.2 Create `frontend/src/services/briefingService.ts` with `getBriefing(id: string): Promise<Briefing>` (explicit return type, no React imports)

## 8. Frontend: VoiceBriefing component

- [x] 8.1 Create `frontend/src/components/VoiceBriefing.tsx`: "Brief me" button → `getBriefing` → render text panel + speak via `speechSynthesis` with Play/Stop; feature-detect `window.speechSynthesis` (text-only fallback); subtle marker when `source === "fallback"`; add `data-testid` attributes
- [x] 8.2 Mount `VoiceBriefing` in `frontend/src/pages/ElevatorDetail.tsx` in a "Pre-visit briefing" section for `in_model_scope` units

## 9. Review and Update Existing Tests (MANDATORY)

- [x] 9.1 Review `tests/unit/test_elevator_service.py` and `tests/integration/test_elevators_router.py` for tests affected by the new route/service
- [x] 9.2 Update any tests invalidated by this change (none expected — additive change)

## 10. Unit Tests and DB State Verification (MANDATORY)

- [x] 10.1 Capture pre-test DB baseline (table counts) — expect no change (briefing not persisted)
- [x] 10.2 Run targeted tests: `backend/venv/bin/python -m pytest tests/unit/test_briefing_service.py -v`
- [x] 10.3 Run full unit suite: `backend/venv/bin/python -m pytest tests/unit/ -v --cov=app --cov-report=term-missing`
- [x] 10.4 Verify post-test DB state unchanged
- [x] 10.5 Create report `reports/2026-06-15-step-10-unit-tests.md`
- [x] 10.6 Mark complete only after report exists and tests pass

## 11. Manual Endpoint Testing (MANDATORY — AGENT MUST EXECUTE)

- [x] 11.1 Ensure backend is running (`docker compose up backend db -d` or local uvicorn) with AWS credentials available to boto3
- [x] 11.2 Test `GET /api/elevators/ELV-001/briefing` → 200, verify non-empty `text` and `source`
- [x] 11.3 Test `GET /api/elevators/UNKNOWN/briefing` → 404 `{"detail":"Elevator not found"}`
- [x] 11.4 Force the fallback path (e.g. set an invalid `BEDROCK_MODEL_ID`) → 200 with `source:"fallback"`; restore config afterwards
- [x] 11.5 No DB mutation to restore (read-only endpoint)
- [x] 11.6 Create report `reports/2026-06-15-step-11-endpoint-testing.md`

## 12. E2E Testing with Playwright MCP (MANDATORY — AGENT MUST EXECUTE)

- [x] 12.1 Ensure frontend and backend are running
- [x] 12.2 Navigate to an in-scope unit detail page; verify the "Brief me" control renders
- [x] 12.3 Click "Brief me"; verify the briefing text appears (stub/observe TTS; assert Stop control present)
- [x] 12.4 Verify text-only behaviour path and the `fallback` marker scenario
- [x] 12.5 No DB state to restore
- [x] 12.6 Create report `reports/2026-06-15-step-12-e2e-testing.md`

## 13. Update Technical Documentation (MANDATORY)

- [x] 13.1 Update `docs/api-spec.yml`: new `briefing` tag, `GET /api/elevators/{id}/briefing` path, and `Briefing` schema
- [x] 13.2 Update `docs/data-model.md`: note the briefing is generated on demand and NOT persisted
- [x] 13.3 Document the `BEDROCK_*` env vars in `docker-compose.prod.yml` / README

## 14. Deployment configuration (one-time)

- [x] 14.1 Add `BEDROCK_REGION` / `BEDROCK_MODEL_ID` to the production compose env
- [x] 14.2 Grant the production EC2 instance role `bedrock:InvokeModel` on the EU inference-profile ARN and the routed foundation-model ARNs; verify the endpoint returns `source:"bedrock"` in production
