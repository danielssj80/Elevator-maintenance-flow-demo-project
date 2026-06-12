---
description: Mandatory steps for creating and executing OpenSpec tasks.md files. Enforces testing discipline and agent execution requirements.
alwaysApply: true
---

# OpenSpec Tasks: Mandatory Steps

## 1. Read `openspec/config.yaml` First

**Before creating or updating any `tasks.md`**, read `openspec/config.yaml` to understand:
- Mandatory steps configured for this project
- Branch naming conventions
- Task structure requirements

## 2. Mandatory Task Structure

All `tasks.md` files must follow this structure. Steps must appear in this order:

### Step 0: Create Feature Branch (MUST BE FIRST)

```markdown
## 0. Setup: Create Feature Branch

- [ ] 0.1 Create branch `feature/<change-name>` from `main`
- [ ] 0.2 Verify current branch with `git branch --show-current`
```

### Mandatory Steps (always include, numbered after implementation steps)

```
Step N:   Review and update existing tests
Step N+1: Run unit tests and verify DB state
Step N+2: Manual endpoint testing with httpx/curl (AGENT MUST EXECUTE)
Step N+3: E2E testing with Playwright MCP (MANDATORY if frontend changes)
Step N+4: Update technical documentation
```

---

## 3. Mandatory Testing Steps — Agent Must Execute

**CRITICAL:** The agent must execute all testing steps itself. Never delegate testing to the user. A task can only be marked `[x]` after the agent has executed and verified the test.

---

### Step N+1: Run Unit Tests and Verify DB State

**Agent responsibility:** Execute pytest, capture pre/post DB state, create a report.

**Implementation steps:**

1. Capture pre-test DB state (relevant table counts or key records).
2. Run targeted unit tests for the changed modules:
   ```bash
   backend/venv/bin/python -m pytest tests/unit/test_<module>.py -v
   ```
3. Run the full unit test suite:
   ```bash
   backend/venv/bin/python -m pytest tests/unit/ -v --cov=app --cov-report=term-missing
   ```
4. Verify post-test DB state matches pre-test state (no unintended mutations).
5. Create a report in `openspec/changes/<change-name>/reports/` with filename:
   `YYYY-MM-DD-step-N+1-unit-tests.md`
6. Mark step complete **only after** report is created and tests pass.

**Report template:**

```markdown
# Step N+1 Report — Unit Tests

- Date: YYYY-MM-DD
- Change: <change-name>

## Commands Executed
- `<command>`

## Results
- Targeted tests: X passed, Y failed, Z skipped
- Full suite: X passed, Y failed, Z skipped
- Coverage: X%

## DB State
- Pre-test: <counts / key records>
- Post-test: <counts / key records>
- State restored: Yes / Not needed

## Outcome
PASS / FAIL
```

---

### Step N+2: Manual Endpoint Testing (AGENT MUST EXECUTE)

**Agent responsibility:** Test every endpoint affected by the change using `httpx` or `curl`. Never ask the user to run these.

**Implementation steps:**

1. Ensure the backend is running:
   ```bash
   docker compose up backend db -d
   # or
   cd backend && uvicorn app.main:app --reload
   ```

2. For each affected endpoint, execute the test and document the result:

   **GET endpoints:**
   ```bash
   curl -s http://localhost:8000/api/elevators | python3 -m json.tool
   ```

   **POST endpoints (create then restore DB state):**
   ```bash
   # Test
   curl -s -X POST http://localhost:8000/api/elevators/ELV-001/report \
     -H "Content-Type: application/json" \
     -d '{"technician_name": "Test User", "visit_date": "2026-06-05", "failure_found": false, "notes": "test"}' \
     | python3 -m json.tool

   # Restore DB state after testing (delete created record)
   ```

   **PUT/PATCH endpoints (restore original values after test).**
   **DELETE endpoints (recreate the record after test).**

3. Test error cases:
   - `404` for unknown resource IDs
   - `422` for invalid request bodies

4. Create a report `YYYY-MM-DD-step-N+2-endpoint-testing.md` in the reports folder.

5. Mark step complete **only after** all endpoints pass and DB state is restored.

**Report template:**

```markdown
# Step N+2 Report — Endpoint Testing

- Date: YYYY-MM-DD
- Change: <change-name>

## Endpoints Tested

### GET /api/elevators
- Command: `curl -s http://localhost:8000/api/elevators`
- Status: 200 ✓
- Response sample: <first item>

### POST /api/elevators/{id}/report
- Command: `curl -X POST ...`
- Status: 201 ✓
- DB state restored: Yes

## Error Cases
- GET /api/elevators/unknown → 404 ✓
- POST with missing field → 422 ✓

## Outcome
PASS / FAIL
```

---

### Step N+3: E2E Testing with Playwright MCP (if frontend changes)

**When this applies:** Any change that modifies UI behavior or adds a new user workflow.

**Agent responsibility:** Use Playwright MCP tools to execute the full user workflow. Never delegate to the user.

**Implementation steps:**

1. Ensure frontend and backend are running:
   ```bash
   docker compose up -d
   # or
   cd frontend && npm run dev  (+ backend separately)
   ```

2. Use Playwright MCP to navigate and interact:
   - `browser_navigate` to open the app
   - `browser_snapshot` to verify initial state
   - `browser_click`, `browser_fill`, `browser_select_option` for interactions
   - `browser_wait_for` for async operations
   - `browser_take_screenshot` at key verification points

3. Cover the scenarios defined in the OpenSpec `specs/` files for this change.

4. Test error scenarios (validation errors, empty states, not-found states).

5. Verify data persistence: after creating/updating via UI, confirm DB state.

6. Restore DB state after any data-mutating test.

7. Create `YYYY-MM-DD-step-N+3-e2e-testing.md` report in the reports folder.

8. Mark step complete **only after** all scenarios pass.

**Report template:**

```markdown
# Step N+3 Report — E2E Testing

- Date: YYYY-MM-DD
- Change: <change-name>

## Scenarios Executed

### Scenario: <name from spec>
- Steps: navigate → interact → verify
- Result: PASS ✓
- Screenshot: <path or description>

## Error Scenarios
- <scenario>: PASS ✓

## DB State
- Restored: Yes / Not needed

## Outcome
PASS / FAIL
```

---

### Step N+4: Update Technical Documentation

Read `docs/documentation-standards.md` and update whichever `docs/` files are affected by this change:

- New endpoint → update `docs/api-spec.yml`
- New entity or field → update `docs/data-model.md`
- New pattern or library → update `backend-standards.md` or `frontend-standards.md`
- No doc change needed → note "No documentation update required" in the task

---

## 4. Verification Checklist

Before finalising a `tasks.md`, verify:

- [ ] Step 0 (feature branch) is the **first** step
- [ ] All mandatory steps from `openspec/config.yaml` are included
- [ ] Steps are numbered sequentially
- [ ] Mandatory steps are labelled `(MANDATORY)`
- [ ] Steps N+2 and N+3 state **"AGENT MUST EXECUTE"**
- [ ] Report paths follow `openspec/changes/<change-name>/reports/YYYY-MM-DD-step-*.md`
- [ ] DB state restoration is described for all mutating endpoint tests
- [ ] E2E step is included if the change touches the frontend

---

## 5. Example Structure

```markdown
## 0. Setup: Create Feature Branch (MANDATORY)

- [ ] 0.1 Create branch `feature/elevator-risk-dashboard` from `main`
- [ ] 0.2 Verify branch: `git branch --show-current`

## 1. Backend: Risk Score Service (TDD)

- [ ] 1.1 Write failing test for `calculate_risk_level()`
- [ ] 1.2 Implement `calculate_risk_level()` in `elevator_service.py`
- [ ] 1.3 Test passes

## 2. Backend: Alembic Migration

- [ ] 2.1 Add `risk_score` column to `Elevator` ORM model
- [ ] 2.2 Generate migration: `alembic revision --autogenerate -m "add risk_score"`
- [ ] 2.3 Review generated migration file
- [ ] 2.4 Apply: `alembic upgrade head`

## 3. Frontend: Risk Badge Component

- [ ] 3.1 Create `RiskBadge.tsx` component
- [ ] 3.2 Add `data-testid="risk-badge"` attribute
- [ ] 3.3 Render badge in `Dashboard.tsx`

## 4. Review and Update Existing Tests (MANDATORY)

- [ ] 4.1 Review `tests/unit/test_elevator_service.py` for affected tests
- [ ] 4.2 Update any tests that are invalidated by this change

## 5. Unit Tests and DB State Verification (MANDATORY)

- [ ] 5.1 Capture pre-test DB baseline
- [ ] 5.2 Run targeted unit tests
- [ ] 5.3 Run full test suite with coverage
- [ ] 5.4 Verify post-test DB state
- [ ] 5.5 Create report `reports/YYYY-MM-DD-step-5-unit-tests.md`
- [ ] 5.6 Mark complete only after report exists and tests pass

## 6. Manual Endpoint Testing (MANDATORY — AGENT MUST EXECUTE)

- [ ] 6.1 Ensure backend is running
- [ ] 6.2 Test GET /api/elevators with curl, verify response
- [ ] 6.3 Test GET /api/elevators/{id}, verify risk fields
- [ ] 6.4 Test 404 for unknown elevator ID
- [ ] 6.5 Create report `reports/YYYY-MM-DD-step-6-endpoint-testing.md`

## 7. E2E Testing with Playwright MCP (MANDATORY — AGENT MUST EXECUTE)

- [ ] 7.1 Ensure frontend and backend are running
- [ ] 7.2 Navigate to dashboard, verify risk badges render
- [ ] 7.3 Verify high-risk elevators appear with correct styling
- [ ] 7.4 Restore DB state if needed
- [ ] 7.5 Create report `reports/YYYY-MM-DD-step-7-e2e-testing.md`

## 8. Update Technical Documentation (MANDATORY)

- [ ] 8.1 Update `docs/api-spec.yml` with risk fields in response schema
- [ ] 8.2 Update `docs/data-model.md` with `risk_score` field
```

---

## 6. Agent Execution Requirements

When implementing tasks from `tasks.md` (via `/apply`), the agent MUST:

1. **Execute all tests itself** — never ask the user to run pytest, curl, or Playwright tests.
2. **Mark tasks `[x]` only after** successful execution, DB state verification, and report creation.
3. **Never skip testing steps** — even if the code change looks trivial.
4. **Document every test run** — commands executed, output observed, DB state before and after.
5. **Start servers if needed** — the agent must start the backend and/or frontend if they are not running before executing tests.
