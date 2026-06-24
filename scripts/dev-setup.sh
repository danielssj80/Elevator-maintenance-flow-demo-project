#!/usr/bin/env bash
#
# dev-setup.sh — prepare the dev/test Docker stack on any Linux host.
#
# Idempotent and host-agnostic: pulls the database image and builds the
# application images defined in docker-compose.yml. It does NOT start any
# service and does NOT touch persisted data, so it is safe to re-run.
#
# Used identically in three places:
#   - Claude Code on the web: as the cloud environment's setup script
#     (`bash scripts/dev-setup.sh`), so images are cached in the snapshot.
#   - A dedicated dev EC2 box (future): same command, no changes.
#   - A local laptop: same command.
#
# Requires: docker + docker-compose (v1) available on PATH.
# See docs/dev-workflow.md for how to run the stack and the test suite.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

echo "==> dev-setup: repo root = $REPO_ROOT"

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker is not installed or not on PATH." >&2
  exit 1
fi

# Detect the available Docker Compose CLI: prefer v2 (the `docker compose`
# plugin shipped by the Claude Code web sandbox), fall back to v1 (the
# `docker-compose` binary used on the production host). This keeps the script
# portable across the web sandbox, a dev EC2, and a laptop.
if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  echo "ERROR: no Docker Compose CLI found ('docker compose' v2 or 'docker-compose' v1)." >&2
  exit 1
fi
echo "==> dev-setup: using compose CLI: $COMPOSE"

echo "==> dev-setup: pulling the database image (db)"
$COMPOSE pull db

echo "==> dev-setup: building application images (migrate, backend, frontend)"
$COMPOSE build

echo "==> dev-setup: done. Images are ready; no services were started."
echo "    Start the stack with:   docker-compose up -d"
echo "    Run tests in Docker:    see docs/dev-workflow.md"
