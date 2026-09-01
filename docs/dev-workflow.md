---
description: How to develop this project safely without breaking the production demo — a two-track workflow (Claude Code on the web for non-Docker work; local/dev-EC2 for the Docker stack). Branch → PR → merge → auto-deploy.
alwaysApply: false
---

# Development Workflow

This project uses a **two-track** development workflow:

- **Track A — Claude Code on the web** ([claude.ai/code](https://claude.ai/code)):
  non-Docker work — Python/ML (e.g. M1 offline training), code edits, docs, and
  opening PRs. No local-machine dependency.
- **Track B — local machine or the dedicated dev EC2**: the full Docker Compose
  stack and the backend/integration/E2E tests, via `scripts/dev-setup.sh`.

The split exists because the Claude Code web sandbox **cannot practically run the
Docker stack** (see [§4](#4-why-the-web-sandbox-is-not-a-docker-host)). It runs
language toolchains directly, which is all M1 needs.

## 1. The golden rule: production deploys from `main`

A push to `main` auto-deploys to production (`https://elevator.dsaavedra.dev`) via
GitHub Actions → OIDC → SSM. To protect the live demo:

- **`main` is branch-protected**: PR required, `enforce_admins` on, no direct
  pushes, no force-push, no deletion. Even an admin or an agent cannot push
  straight to `main`.
- All work happens on `feature/*` branches and reaches production **only** through
  a reviewed PR merge.

In a Claude Code **web** session this is doubly enforced: the sandbox's GitHub proxy
restricts every session to pushing **only its own working branch**, so a cloud
session can never touch `main` directly.

```
feature branch  →  push  →  Pull Request  →  review + merge (you)  →  auto-deploy
```

The project owner reviews and merges PRs; agents do not merge.

## 2. Track A — Claude Code on the web (non-Docker)

Use the web sandbox for Python/ML work (M1), edits, docs, and PRs.

1. In [claude.ai/code](https://claude.ai/code), connect your GitHub account and this
   repository; start a session on a `feature/*` branch.
2. **No special environment setup is required for non-Docker work.** Leave the
   environment **Setup script empty** (a Docker-oriented setup script will fail —
   see §4). Do **not** put AWS/Bedrock credentials in the environment (no secrets
   store; env vars are visible to anyone who can edit the environment).
3. For Python work, use a venv on the host (the sandbox's proxy CA is trusted on the
   host, so `pip` works there):

   ```bash
   python3 -m venv .venv
   .venv/bin/pip install --upgrade pip
   .venv/bin/pip install <your-deps>     # e.g. xgboost scikit-learn pandas for M1
   ```

   Note: the sandbox ships Python 3.11 (the project targets 3.12) — fine for M1
   offline work; keep version-sensitive code in mind.

### Moving sessions between web and terminal

- `--remote` starts/continues a task in the cloud from your terminal.
- `--teleport` pulls a cloud session down to your local terminal.

### Cost / quota note

Cloud sessions have **no separate compute charge** for the VM, but they draw on the
**shared Claude usage quota** of your account. On Pro, prefer **one task at a time**.

## 3. Track B — local or dev EC2 (full Docker stack + tests)

Run the Docker stack and tests on a local machine or the dedicated dev EC2 (see the
"Provision a dedicated dev EC2 box" backlog task). Use whichever Compose CLI you
have — `docker compose` (v2) or `docker-compose` (v1); `scripts/dev-setup.sh`
auto-detects it.

Prepare images (idempotent; run once per host, or after dependency changes):

```bash
bash scripts/dev-setup.sh
```

Pick the Compose CLI for the commands below:

```bash
docker compose version >/dev/null 2>&1 && COMPOSE="docker compose" || COMPOSE="docker-compose"
```

Start the stack:

```bash
$COMPOSE up -d             # db → migrate → backend → frontend → observability → n8n
```

Since M5 that one command also brings up the OpenTelemetry Collector, the
Grafana/Tempo/Prometheus bundle (`lgtm`, Grafana on **:3001** because the
frontend owns 3000), the `inference` service and self-hosted **n8n** on
**:5678**. Queue mode is opt-in and needs **both** halves:

```bash
N8N_EXECUTIONS_MODE=queue $COMPOSE --profile queue up -d
```

The profile alone starts a worker while the main process stays in regular mode
and executes everything itself; nothing reports the mismatch. See
[orchestration.md](./orchestration.md).

**Two things cache at startup and will waste your afternoon otherwise:**

- The frontend's nginx resolves `backend` **once**. Recreate the `backend`
  container and it keeps proxying to the old IP, so `localhost:3000` serves a
  502 — which behind the SPA looks like an empty fleet, not like an outage.
  `$COMPOSE restart frontend` after any backend recreate.
- The Collector and Grafana only read their mounted configuration at startup.
  Edit a collector config or a dashboard JSON and you need
  `--force-recreate` on that service before the change exists.

Bedrock is optional locally: without AWS credentials in the root `.env` the
briefing endpoint answers `source: "fallback"` and n8n's agent nodes fall back to
a fixed scenario. Everything else works.

Run the backend unit suite against a dedicated test database. The production backend
image ships without dev dependencies (pytest is installed ephemerally — tracked as a
backlog improvement to bake a dev image target). The Compose project name — used for
the default network and image names — is the **lowercased** repo directory name:

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

## 4. Why the web sandbox is not a Docker host

Validated live in a real web session — the sandbox cannot practically run the Docker
stack, for cumulative reasons:

- **Daemon not auto-started** — `dockerd` must be launched per session (the cache
  stores files, not processes).
- **Setup script CWD is not the repo root** — relative paths fail (`exit 127`); an
  absolute path is required.
- **`Trusted` network blocks Docker Hub's CDN** — image pulls `403` from
  `production.cloudfront.docker.com` (Trusted allows the `cloudflare` variant, not
  `cloudfront`); needs **Full** or **Custom**.
- **The wall — image builds fail TLS** — `pip`/`npm` inside `docker build` hit
  `CERTIFICATE_VERIFY_FAILED` (self-signed cert in chain), because the sandbox's
  security proxy does TLS interception with a CA that is trusted on the host but
  **not inside build containers**.

Working around the last point means hacking the production Dockerfiles or pushing
pre-built images to a registry — not worth it. M1 needs none of it, so the Docker
loop lives on **local / the dev EC2** instead.

## 5. The dedicated dev EC2 (recommended next infra step)

`scripts/dev-setup.sh` is host-agnostic, so the dev EC2 (separate from production)
bootstraps the full Docker stack with the same command and **no changes**. Because
the web sandbox can't run docker-in-docker, this box is the reliable home for the
Docker loop — see the "Provision a dedicated dev EC2 box" backlog task.
