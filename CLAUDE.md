# CLAUDE.md
---
description: Entry point for all AI agents working on this project. Defines core principles, workflow, and references to detailed standards.
alwaysApply: true
---

## 1. Core Principles

See [docs/base-standards.md](./docs/base-standards.md) for the full set of development principles and workflow rules. Summary:

- **Small tasks, one at a time** — never advance more than one step without confirmation.
- **Test-Driven Development** — write the failing test before the implementation.
- **Type Safety** — Python type hints and TypeScript strict mode, no exceptions.
- **Clear Naming** — code should read as documentation.
- **Incremental Changes** — small, focused changes over large modifications.
- **Question Assumptions** — if something is ambiguous, ask before implementing.

## 2. Language

Converse with the user in **Spanish**. All technical artifacts must be written in **English** — see `docs/base-standards.md` §2 for the full list.

## 3. Specific Standards

Detailed guidelines per area:

- [docs/base-standards.md](./docs/base-standards.md) — core principles, OpenSpec workflow, planning model, git conventions
- [docs/backend-standards.md](./docs/backend-standards.md) — FastAPI, SQLAlchemy, Pydantic v2, pytest + httpx
- [docs/frontend-standards.md](./docs/frontend-standards.md) — React 19, Vite, Tailwind, Playwright
- [docs/documentation-standards.md](./docs/documentation-standards.md) — when to update Notion / OpenSpec / docs/
- [docs/openspec-tasks-mandatory-steps.md](./docs/openspec-tasks-mandatory-steps.md) — mandatory checklist for tasks.md creation and execution
- [docs/data-model.md](./docs/data-model.md) — elevator domain entities, fields, business rules
- [docs/api-spec.yml](./docs/api-spec.yml) — OpenAPI 3.1 specification

## 4. Project Skills

- Skills live in `.claude/skills/`.
- When a request matches a skill, load and follow the corresponding `SKILL.md` automatically before continuing.
- Also load any referenced files in the skill folder (e.g. `references/*.md`) when the skill requires them.

Available skills:

| Skill | Trigger |
|---|---|
| `enrich-us` | User provides a Notion task to enrich before starting a change |
| `adversarial-review` | User requests a red-team or independent review before archiving |
| `commit` | User wants to commit changes and/or create a PR |
| `update-docs` | User asks to update documentation, or before any commit |
| `show-spec-working` | User asks to "show", "demo", or "prove" a feature works |
| `using-git-worktrees` | User wants to start isolated feature work |
| `explain` | User asks to understand a concept behind a question |
| `meta-prompt` | User wants to improve a prompt using best practices |
| `code-auditing` | User requests a code quality or security audit |
| `writing-skills` | User wants to write or improve a skill |

## 5. OpenSpec Workflow

This project uses OpenSpec for all feature development. Full workflow in `docs/base-standards.md` §5. Quick reference:

```
enrich-us <notion-url>        → enrich Notion task with technical detail
openspec new change <name>    → create change scaffolding
fill proposal / specs / design / tasks.md
/apply                        → implement tasks one at a time (TDD)
/adversarial-review           → independent review before archiving
/archive                      → archive the completed change
/commit                       → commit + PR
update Notion task to done
```

**OpenSpec is the source of truth during implementation.** Never make code-only fixes between `/apply` and `/archive` without updating the relevant spec artifacts first.

## 6. Notion

This project is tracked in Notion under **Elevator Maintenance Flow Demo Project**.

- Notion = high-level project management (features, milestones, status).
- OpenSpec = detailed implementation contract (scenarios, specs, tasks).
- Use `/enrich-us <notion-url>` to bridge a Notion task into an OpenSpec change.
- All Notion content must be in English.

## 7. Planning Model

Planning and spec-creation workflows must use **Fable** (the most capable model). This applies to `enrich-us` and filling OpenSpec artifacts. Switch manually via `/model` before running these workflows, and consider switching back to a lighter model for routine implementation afterwards.
