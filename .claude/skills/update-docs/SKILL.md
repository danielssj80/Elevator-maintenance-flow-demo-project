---
name: update-docs
description: Identify and update required documentation after implementing a change — across Notion, OpenSpec, and docs/.
author: adapted from LIDR.co
version: 1.0.0
---

# update-docs Skill

Use when the user asks to update documentation, before committing a change, or after archiving an OpenSpec change.

## Decision Tree: What to Update Where

Read `docs/documentation-standards.md` first, then apply this logic:

```
Was there a status change? (feature done, task completed, milestone reached)
  → Update Notion

Did the change affect spec-level behaviour, scenarios, or requirements?
  → Update the OpenSpec artifacts (specs/, design.md) for the active change

Did the change introduce a new pattern, library, endpoint, or data model field?
  → Update the relevant file in docs/
    - New endpoint or schema change       → docs/api-spec.yml
    - New entity or field                 → docs/data-model.md
    - New backend pattern or library      → docs/backend-standards.md
    - New frontend pattern or library     → docs/frontend-standards.md
    - New documentation process change    → docs/documentation-standards.md
    - New standard that applies globally  → docs/base-standards.md

Did nothing above apply?
  → Note "No documentation update required" and explain why
```

## Workflow

### Step 1 — Determine scope

If `$ARGUMENTS` contains a change name or description, use that as scope.
Otherwise, infer from the current session: active OpenSpec change, recent git diff, or what the user just implemented.

### Step 2 — Identify affected documentation

For each layer, decide if an update is needed:

**Notion** — needs update if:
- A task moved to done
- A milestone was reached
- Project status changed

**OpenSpec** — needs update if:
- A scenario was found to be missing or incorrect during implementation
- A requirement changed in scope between `/apply` and `/archive`
- A design decision was revised

**`docs/`** — needs update if:
- A new endpoint was added or an existing one changed → `api-spec.yml`
- A new DB field or entity was added → `data-model.md`
- A new library, pattern, or architectural decision was introduced → relevant standards file

### Step 3 — Propose specific changes

For each file that needs updating, state:
1. **Which file** to update
2. **Which section** within the file
3. **Exactly what text** to add, modify, or remove

Do not apply changes until the user confirms.

### Step 4 — Apply after confirmation

Once the user approves, apply each change. Then summarise:
- Files updated: list with one-line description of what changed
- Files not updated: list with reason

## Rules

- **Never apply doc changes without user approval** (except during `/apply` where tasks.md Step N+4 explicitly requires it — in that case, apply and report).
- **Propose specific edits**, not vague improvements ("update the testing section" is not acceptable — show the exact text).
- **One file at a time** — do not batch unrelated doc changes.
- **English only** — all documentation content must be in English.
