---
description: How to develop this project safely from Claude Code on the web (and locally), without breaking the production demo. Branch → PR → merge → auto-deploy.
alwaysApply: false
---

# Development Workflow

This project can be developed entirely from **Claude Code on the web**
([claude.ai/code](https://claude.ai/code)) — working directly against the GitHub
repo, with no dependency on any single local machine — or from a local terminal.
The same setup primitive (`scripts/dev-setup.sh`) works in all environments.

## 1. The golden rule: production deploys from `main`

A push to `main` auto-deploys to production (`https://elevator.dsaavedra.dev`) via
GitHub Actions → OIDC → SSM. To protect the live demo:

- **`main` is branch-protected**: pull request required, `enforce_admins` on, no
  direct pushes, no force-push, no deletion. Even an admin (or an agent) cannot
  push straight to `main`.
- All work happens on `feature/*` branches and reaches production **only** through
  a reviewed PR merge.

In a Claude Code **web** session this is doubly enforced: the sandbox's GitHub proxy
restricts every session to pushing **only its own working branch**, so a cloud
session can never touch `main` directly.

## 2. The flow

```
feature branch  →  push  →  Pull Request  →  review + merge (you)  →  auto-deploy
```

1. Create a `feature/<short-name>` branch.
2. Implement (TDD per the standards). Run the stack and tests in Docker (§4).
3. Push the branch and open a PR.
4. **You review and merge** the PR on GitHub (the project owner merges; agents do
   not merge).
5. The merge to `main` triggers the production deploy. Verify the result.

## 3. Working from Claude Code on the web

### One-time: connect the repo and configure the environment

1. In [claude.ai/code](https://claude.ai/code), connect your GitHub account and
   select this repository.
2. Configure the **cloud environment** (cloud icon → environment settings):
   - **Network access**: **Trusted** is sufficient. It already allows GitHub, PyPI,
     npm, and Docker Hub — everything `scripts/dev-setup.sh` needs.
   - **Setup script**: set it to
     ```bash
     bash scripts/dev-setup.sh
     ```
     It runs once and the resulting filesystem (including pulled/built Docker
     images) is **cached** in the environment snapshot, so later sessions start
     fast and skip it.
   - **Environment variables / secrets**: **do not** put AWS/Bedrock credentials
     here. Claude Code web has no dedicated secrets store yet, and env vars are
     visible to anyone who can edit the environment. Dev/test runs without AWS:
     PostgreSQL is local to the Compose stack, and the briefing endpoint uses its
     deterministic fallback when Bedrock is unreachable.

### Moving sessions between web and terminal

- `--remote` starts/continues a task in the cloud from your terminal.
- `--teleport` pulls a cloud session down to your local terminal.

### Cost / quota note

Cloud sessions have **no separate compute charge** for the VM, but they draw on the
**shared Claude usage quota** of your account. On Pro, prefer **one task at a time**
(parallel sessions consume quota proportionally). Sessions stop after inactivity and
the environment is reclaimed, but the cached filesystem persists.

## 4. Running the stack and tests in Docker

Build and test **inside Docker**, not on the host. Use whichever Compose CLI your
environment provides — the **`docker compose`** v2 plugin (e.g. the Claude Code web
sandbox) or the **`docker-compose`** v1 binary (the production host convention).
`scripts/dev-setup.sh` auto-detects this; the examples below select it explicitly:

```bash
# Prefer v2 plugin, fall back to v1:
docker compose version >/dev/null 2>&1 && COMPOSE="docker compose" || COMPOSE="docker-compose"
```

Prepare images (idempotent; run once per environment, or after dependency changes):

```bash
bash scripts/dev-setup.sh
```

Start the stack:

```bash
$COMPOSE up -d              # db → migrate → backend → frontend
```

Run the backend unit suite against a dedicated test database. The production backend
image ships without dev dependencies (pytest is installed ephemerally for the run —
tracked as a backlog improvement to bake a dev image target). The Compose project
name — used for the default network and image names — is the **lowercased**
repository directory name:

```bash
PROJECT="$(basename "$PWD" | tr '[:upper:]' '[:lower:]')"

$COMPOSE up -d db
docker exec "$($COMPOSE ps -q db)" \
  createdb -U user elevator_test_db 2>/dev/null || true

docker run --rm \
  --network "${PROJECT}_default" \
  -v "$PWD/backend":/app -w /app \
  -e TEST_DATABASE_URL="postgresql+asyncpg://user:password@db:5432/elevator_test_db" \
  "${PROJECT}-backend:latest" \
  sh -c "pip install -q -r requirements-dev.txt && python -m pytest tests/unit/ -q"
```

E2E tests use the Playwright MCP against the running stack (see
[frontend-standards.md](./frontend-standards.md)).

## 5. Portability to a dedicated dev EC2 (future)

`scripts/dev-setup.sh` is intentionally host-agnostic. On a future dedicated dev EC2
(separate from production — see the "Provision a dedicated dev EC2 box" backlog
task), the same command bootstraps the dev stack with **no changes**. A dev box
avoids consuming Claude usage quota and survives session inactivity, at the cost of
an instance to maintain. The web sandbox and the dev box are interchangeable.
