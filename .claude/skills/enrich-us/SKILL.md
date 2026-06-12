---
name: enrich-us
description: Read a Notion task and enhance it with complete, implementation-ready technical detail before creating an OpenSpec change.
author: adapted from LIDR.co
version: 1.0.0
---

# enrich-us Skill

Use when the user wants to start a new feature or change and provides a Notion task URL or task name.

## Purpose

Transform a high-level Notion task (what + why) into an implementation-ready specification (how), then optionally write the enriched content back to Notion before creating the OpenSpec change.

## Inputs

`$ARGUMENTS` may contain:
- A Notion page URL (e.g. `https://www.notion.so/...`)
- A task name or keywords to search for in Notion
- Nothing — in which case ask the user for the Notion task reference

## Workflow

### Step 1 — Load the Notion task

If a URL was provided, fetch it directly:
```
notion-fetch: { url: "<url>" }
```

If only keywords were provided, search first:
```
notion-search: { query: "<keywords>" }
```
Then fetch the matching page.

If no input was provided, ask: "Which Notion task should I enrich? Please share the URL or title."

### Step 2 — Understand the task

Read the page content and extract:
- **Title**: what this task is called
- **Description**: what problem it solves and why now
- **Any acceptance criteria or notes** already written

### Step 3 — Enrich with technical detail

Acting as a product expert with technical knowledge of this project, produce an enhanced version that includes all of the following (where applicable):

1. **Full functionality description** — what the system will do, stated precisely
2. **Affected backend areas** — routers, services, repositories, models, schemas impacted
3. **Affected frontend areas** — pages, components, services, hooks impacted
4. **API changes** — new or modified endpoints with URL, method, request/response shape
5. **Data model changes** — new fields, tables, or relationships
6. **Acceptance criteria** — WHEN/THEN scenarios (one per testable behaviour)
7. **Definition of done** — checklist of what "complete" means (code + tests + docs)
8. **Non-functional requirements** — security, performance, observability concerns if relevant
9. **Out of scope** — explicit list of what this change does NOT cover

Use the project's technical context from `docs/` (backend-standards.md, frontend-standards.md, data-model.md, api-spec.yml) to make the enrichment implementation-ready.

### Step 4 — Present the enriched version in chat

Show the result in this format:

```markdown
## Original
<original Notion content>

## Enhanced
<enriched version with all sections from Step 3>
```

### Step 5 — Ask before updating Notion

After showing the enriched content, ask:

> "Do you want me to update the Notion page with the enhanced version?"

- If **yes**: update the page using `notion-update-page`, appending the enhanced content after the original with a clear `## Enhanced` heading. Then confirm: "Notion page updated."
- If **no**: confirm: "No update made. You can copy the enhanced version above manually."

### Step 6 — Suggest next step

After confirming the enrichment (whether or not Notion was updated), suggest:

> "Ready to create the OpenSpec change? Run: `openspec new change <name>` where `<name>` is a short kebab-case identifier for this feature."

## Notes

- This skill only enriches and proposes. It does not create the OpenSpec artifacts — that is the user's next step (`openspec new change` + filling proposal/specs/design/tasks).
- If the Notion task is already very detailed, say so and confirm with the user before adding more content.
- Write all enriched content in **English**.
