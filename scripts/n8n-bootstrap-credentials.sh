#!/usr/bin/env bash
# Create n8n's credentials from the git-ignored root .env, without the UI.
#
# Why a script rather than clicking through the editor: the credentials are
# derived from values that already live in .env, so doing it by hand is a
# transcription step that can go wrong silently — a mistyped ingest token shows
# up as an HTTP 401 inside a workflow node, which reads like a backend problem.
# This also makes the setup reproducible on a fresh machine and after a
# `docker compose down -v`.
#
# n8n encrypts credentials with N8N_ENCRYPTION_KEY on import, so the plaintext
# only ever exists in a temporary file inside the container, which is removed
# before this script exits — including if it fails.
#
# Usage:  ./scripts/n8n-bootstrap-credentials.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ ! -f .env ]]; then
  echo "No .env at the repository root. Copy observability/.env.example and fill it in." >&2
  exit 1
fi

# shellcheck disable=SC1091  # .env is git-ignored and machine-local by design.
set -a; source .env; set +a

# The ingest token is the one the compose file gives the backend, so the default
# here has to match the default there or the workflows get a 401 on a stack
# nobody configured.
# Exported, not just assigned: the python block below is a subprocess and reads
# this from the environment. Assigning it without exporting worked only in a
# shell that happened to have it already, which is a bug that hides itself.
export INGEST_TOKEN="${TELEMETRY_INGEST_TOKEN:-local-dev-ingest-token}"

REMOTE_FILE=/tmp/n8n-credentials-bootstrap.json
cleanup() { docker compose exec -T n8n rm -f "$REMOTE_FILE" >/dev/null 2>&1 || true; }
trap cleanup EXIT

if [[ -z "${AWS_ACCESS_KEY_ID:-}" || "${AWS_ACCESS_KEY_ID}" == "replace_me" ]]; then
  echo "! AWS_ACCESS_KEY_ID is unset or still 'replace_me'."
  echo "  Skipping the Bedrock credential - the AI Agent node will not reach a model."
  echo "  Create an IAM user, attach the existing ElevatorBedrockInvokeNova policy,"
  echo "  and put its keys in .env. Re-run this script afterwards."
fi

# Built with python3, not jq: jq is not installed on the development machine
# (and is not a project dependency), while python3 is already required by the
# backend and used throughout scripts/. A setup script that needs a tool nobody
# has is a setup script that fails on first use.
CREDENTIALS_JSON=$(python3 - <<'PY'
import json, os

creds = []

key = os.environ.get("AWS_ACCESS_KEY_ID", "")
if key and key != "replace_me":
    creds.append({
        "id": "elevatorBedrock01",
        "name": "Elevator Bedrock (local dev)",
        "type": "aws",
        "data": {
            "region": os.environ.get("BEDROCK_REGION") or "eu-north-1",
            "accessKeyId": key,
            "secretAccessKey": os.environ.get("AWS_SECRET_ACCESS_KEY", ""),
        },
    })

creds.append({
    "id": "elevatorIngest01",
    "name": "Elevator ingest token",
    "type": "httpHeaderAuth",
    "data": {
        "name": "X-Ingest-Token",
        "value": os.environ.get("INGEST_TOKEN") or "local-dev-ingest-token",
    },
})

print(json.dumps(creds))
PY
)

echo "$CREDENTIALS_JSON" | docker compose exec -T n8n sh -c "cat > $REMOTE_FILE"
docker compose exec -T n8n n8n import:credentials --input="$REMOTE_FILE"

echo
echo "Imported. n8n encrypts these with N8N_ENCRYPTION_KEY, so they are readable"
echo "only by an n8n process sharing that key — which is why main and every"
echo "worker must be given the same one."
