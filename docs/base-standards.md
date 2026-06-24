---
description: Core development principles and workflow for the Elevator Maintenance project. Single source of truth for all agents. References area-specific standards.
alwaysApply: true
---

# Base Standards

## 1. Core Principles

- **Small tasks, one at a time**: Always work in baby steps. Never advance more than one step without confirmation.
- **Test-Driven Development**: Write a failing test before writing implementation code.
- **Type Safety**: All code must be fully typed — Python type hints and TypeScript strict mode, no exceptions.
- **Clear Naming**: Use clear, descriptive names. Code should read as documentation.
- **Incremental Changes**: Prefer small, focused changes over large modifications.
- **Question Assumptions**: Always question assumptions. If something is ambiguous, ask before implementing.
- **Pattern Detection**: Identify and flag repeated code patterns. Don't duplicate logic.

## 2. Language Standards

All technical artifacts must be written in **English**, without exception:

- Code: variables, functions, classes, comments, error messages, log messages
- Documentation: README, guides, API docs, OpenSpec artifacts
- Notion content (tasks, descriptions, comments)
- Data schemas and database names
- Configuration files and scripts
- Git commit messages and PR descriptions
- Test names and descriptions

## 3. Area-Specific Standards

For detailed standards per area, refer to:

- [Backend Standards](./backend-standards.md) — FastAPI, SQLAlchemy, Pydantic, testing with pytest + httpx
- [Frontend Standards](./frontend-standards.md) — React 19, Vite, Tailwind, testing with Playwright
- [Documentation Standards](./documentation-standards.md) — when to update Notion, OpenSpec, and `docs/`
- [OpenSpec Tasks Mandatory Steps](./openspec-tasks-mandatory-steps.md) — required checklist when creating or executing `tasks.md`
- [Development Workflow](./dev-workflow.md) — developing safely from Claude Code on the web (and locally): branch → PR → merge → auto-deploy, cloud environment setup, running the stack/tests in Docker

## 4. Project Skills

- Skills live in `.claude/skills/`.
- When a request matches a skill, load and follow the corresponding `SKILL.md` automatically before continuing.
- Also load any referenced files in the skill folder (e.g., `references/*.md`) when the skill requires them.

## 5. OpenSpec Workflow

This project uses OpenSpec for all feature development. The full workflow:

```
1. /enrich-us <notion-task-url>   — enrich Notion task with technical detail
2. openspec new change <name>     — create change scaffolding
3. Fill proposal, specs, design, tasks.md artifacts
4. /apply                         — implement tasks one at a time (TDD)
5. /verify                        — validate implementation against spec artifacts
6. /adversarial-review            — independent red-team review before archiving
7. /archive                       — archive the completed change
8. /commit                        — create focused commit + PR
9. Update Notion task to done
```

**OpenSpec is the source of truth during implementation.** Never make code-only fixes between `/apply` and `/archive` without updating the relevant spec artifacts first.

When a change or fix request appears after `/apply` and before `/archive`:

1. Update the affected OpenSpec artifacts (scenarios, specs, `tasks.md`).
2. Only implement code after the artifacts reflect the new request.
3. Re-run verification before archiving.

## 6. Planning Model

Planning and spec-creation workflows must run with **Opus with extended thinking**.

This applies to:
- `enrich-us` skill
- Filling OpenSpec artifacts (proposal, specs, design, tasks)

Before running these workflows, verify the session is using Opus. If not, switch manually via `/model` before continuing.

## 7. Git and Branching

- Branch naming: `feature/<change-name>` (e.g., `feature/elevator-risk-dashboard`)
- One branch per OpenSpec change.
- Commits follow conventional commits format: `feat:`, `fix:`, `test:`, `docs:`, `refactor:`
- Never force-push to `main`.
- PRs are created via the `commit` skill after `/verify` passes.
