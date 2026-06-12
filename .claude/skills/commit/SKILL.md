---
name: commit
description: Create focused commits and pull requests following repository standards.
author: adapted from LIDR.co
version: 1.0.0
---

# commit Skill

Use when the user wants to commit changes and optionally create a Pull Request.

## Arguments

`$ARGUMENTS` may contain:

- **Nothing**: stage and commit all relevant changes, then open a PR.
- **Feature/change name**: stage and commit only the changes that belong to that feature; leave other changes unstaged.
- **No-git mode**: if the user says "no PR", "only commit message", "dry run", or "don't touch git" — output only the proposed commit message and staging plan without running any git commands.

## Process

### Step 0 — No-git mode check

If the user explicitly requested no git operations:
- Determine scope (which files would be staged)
- Write the full commit message (subject + body)
- Output staging plan + message in a copy-pasteable block
- Stop — do not run any git or `gh` commands

### Step 1 — Inspect current state

```bash
git status
git diff
git diff --staged
```

Identify the current branch. If on `main`, decide whether to create a feature branch first.

### Step 2 — Resolve scope

**No arguments**: stage all relevant changes (excluding `.env`, build artifacts, secrets).

**With change name**: map the argument to files that clearly belong to that feature. Stage only those files/hunks. Leave unrelated changes unstaged.

If a file contains both feature-related and unrelated changes, use `git add -p` to stage only the relevant hunks.

### Step 3 — Write the commit message

- Language: **English**
- Format: conventional commits (`feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `chore:`)
- Subject line: short imperative summary, ≤ 72 characters
- Body (if needed): bullet points explaining what changed and why; reference the OpenSpec change name if applicable

```
feat: add risk trend sparkline to elevator detail view

- Renders 6-day risk score trend using Recharts LineChart
- Extracted TrendChart component with data-testid for E2E tests
- Related change: elevator-detail-trend
```

Do not commit `.env` files, secrets, or generated build artifacts.

### Step 4 — Commit and push

Create the commit with the message from Step 3.

Push the branch to remote (`git push origin <branch>`). If it's a new branch, push with `-u`.

### Step 5 — Pull Request

Use `gh` for all GitHub operations.

Create or update the PR:
- **Title**: clear and aligned with the commit (include OpenSpec change name if applicable)
- **Description**: summarise the change set, link to the OpenSpec change directory, note any testing or follow-ups

### Step 6 — Summary

Report:
- Files staged and committed
- PR URL (from `gh` output)
- If feature-scoped: confirm which change was included and what was left unstaged

## Rules

- Do not run `git push --force` unless the user explicitly requests it.
- If push is rejected, report the situation and suggest next steps (pull/rebase) — do not force-push.
- Never commit sensitive files (`.env`, credentials, tokens).
- When arguments are provided, only stage changes tied to that feature — everything else stays in the working tree.
