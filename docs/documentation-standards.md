---
description: Documentation standards — when to update Notion, OpenSpec, and docs/. Covers technical doc structure and AI spec maintenance rules.
alwaysApply: true
---

# Documentation Standards

## Overview

This project uses three distinct documentation layers. Each has a specific purpose and scope. Understanding which layer to update — and when — is mandatory.

```
Notion          — Project management: what we're building, progress, status
OpenSpec        — Implementation contract: how we're building it, in full detail
docs/           — Technical standards: how we always build, for all agents
```

Never mix these layers. A bug fix does not belong in Notion as a task. A coding standard does not belong in OpenSpec as a scenario.

---

## Layer 1: Notion (Project Management)

**Purpose:** High-level project tracking — features, milestones, priorities, and status.

**What belongs here:**
- Feature requests and product ideas
- Milestone and sprint planning
- Task status (to do, in progress, done)
- High-level descriptions of what and why — not how
- Post-release notes and retrospectives

**What does NOT belong here:**
- Implementation details, endpoint definitions, or data schemas
- Acceptance criteria with technical scenarios (→ OpenSpec)
- Code standards or architectural decisions (→ `docs/`)

**When to update:**
- When a feature is created, scoped, or prioritized
- When a task changes status (start, block, complete)
- After `/archive`: update the linked Notion task to "Done" with a reference to the OpenSpec change name

---

## Layer 2: OpenSpec (Implementation Contract)

**Purpose:** Detailed, executable specification for each change — the agreement between intent and code.

**What belongs here:**
- `proposal.md` — motivation, what changes, affected capabilities
- `specs/<capability>/spec.md` — requirements written as WHEN/THEN scenarios
- `design.md` — technical decisions, trade-offs, non-goals
- `tasks.md` — step-by-step implementation checklist including mandatory tests

**What does NOT belong here:**
- General coding standards (→ `docs/`)
- Project status or milestone tracking (→ Notion)
- Architecture patterns that apply across the whole codebase (→ `docs/`)

**When to update:**
- OpenSpec artifacts are created at the start of every feature change via `openspec new change`
- Artifacts must be updated before code if a scope change arrives between `/apply` and `/archive`
- After `/archive`, the change folder moves to `openspec/archive/` — do not delete it

---

## Layer 3: `docs/` (Technical Standards)

**Purpose:** Permanent reference for how to build anything in this project — for agents and humans.

**Files and their purpose:**

| File | When to update |
|---|---|
| `base-standards.md` | Core principles change, workflow changes, new skill added |
| `backend-standards.md` | New library adopted, architecture pattern added/changed, new testing rule |
| `frontend-standards.md` | New library adopted, component pattern changed, routing convention updated |
| `documentation-standards.md` | Documentation process changes |
| `openspec-tasks-mandatory-steps.md` | Testing tooling changes, new mandatory step added |
| `data-model.md` | New entity added, field renamed, relationship changed |
| `api-spec.yml` | Endpoint added, request/response schema changed, new error code defined |

**When to update:**
- Before committing a change that introduces a new pattern, library, or convention not yet described in these docs
- When a standard is violated repeatedly — the fix is to clarify the standard, not just fix the code
- After a `docs/` update is made, note it in the PR description

**What does NOT belong here:**
- Feature-specific behavior (→ OpenSpec)
- Project status (→ Notion)
- One-off decisions that don't apply generally

---

## General Writing Rules

- **Always write in English** — all three layers, no exceptions.
- Be specific and implementation-ready. Vague guidance is worse than no guidance.
- Keep docs short: one clear sentence beats three ambiguous ones.
- When a doc is no longer accurate, fix or delete it immediately — stale docs mislead agents.

---

## AI Spec Maintenance

This rule applies when an interaction reveals a gap or error in these docs.

**The agent must:**

1. **Identify** the relevant doc file and section to update.
2. **Propose** the specific change — not a general summary, but the exact text to add, modify, or remove.
3. **Wait for explicit approval** before writing to any `docs/` file.
4. **Confirm** after the update is applied.

**Anti-patterns to avoid:**

- Applying doc changes without user approval
- Proposing vague improvements ("improve the testing section") instead of specific edits
- Updating multiple unrelated docs in one step
- Making doc changes proactively when there is no direct connection to a user feedback or a real gap observed
