#!/usr/bin/env bash
# Import a published workflow definition into the local n8n, re-attaching the
# credentials the export deliberately stripped.
#
# The two halves have to exist together. `export-n8n-workflow.sh` removes every
# credential block, because publishing one leaks instance internals and makes
# the file un-importable elsewhere. That is correct for the artifact and
# inconvenient for the round trip: re-importing a published file into the live
# instance leaves its HTTP and model nodes with nothing to authenticate with,
# and the workflow then fails at execution with "Credentials not found" — an
# error that says nothing about the export having done its job properly.
#
# So this script maps node types back onto the credential ids that
# `n8n-bootstrap-credentials.sh` creates. Both use fixed literals, so the
# mapping is stable and the round trip is reproducible.
#
# Usage:  ./scripts/n8n-import-workflow.sh n8n/workflows/telemetry-ingest.json [--activate]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

FILE="${1:-}"
ACTIVATE="${2:-}"
if [[ -z "$FILE" || ! -f "$FILE" ]]; then
  echo "Usage: $0 <workflow-file> [--activate]" >&2
  echo >&2
  echo "Available:" >&2
  ls -1 n8n/workflows/*.json 2>/dev/null >&2 || echo "  (none)" >&2
  exit 1
fi

WITH_CREDS=$(mktemp)
trap 'rm -f "$WITH_CREDS"' EXIT

python3 - "$FILE" "$WITH_CREDS" <<'PY'
import json, sys, pathlib

src, dst = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
wf = json.loads(src.read_text())

# Node type -> the credential this repository's bootstrap script creates.
CREDENTIALS = {
    "n8n-nodes-base.httpRequest": (
        "httpHeaderAuth", "elevatorIngest01", "Elevator ingest token"),
    "@n8n/n8n-nodes-langchain.lmChatAwsBedrock": (
        "aws", "elevatorBedrock01", "Elevator Bedrock (local dev)"),
}

attached = []
for node in wf.get("nodes", []):
    mapping = CREDENTIALS.get(node.get("type"))
    if not mapping:
        continue
    kind, cid, cname = mapping
    # An HTTP node only wants a credential if it was configured to use one.
    # Attaching one to an unauthenticated GET would be harmless but misleading.
    if kind == "httpHeaderAuth" and node.get("parameters", {}).get("genericAuthType") != "httpHeaderAuth":
        continue
    node["credentials"] = {kind: {"id": cid, "name": cname}}
    attached.append(f"{node['name']} -> {cname}")

dst.write_text(json.dumps(wf))
print(f"workflow: {wf['name']}  (id {wf['id']})")
for line in attached:
    print(f"  attached {line}")
if not attached:
    print("  no credentials needed")
PY

docker compose cp "$WITH_CREDS" n8n:/tmp/import.json >/dev/null
docker compose exec -T n8n n8n import:workflow --input=/tmp/import.json 2>&1 | grep -viE "postgres 16|migration lock"
docker compose exec -T n8n rm -f /tmp/import.json >/dev/null 2>&1 || true

if [[ "$ACTIVATE" == "--activate" ]]; then
  WF_ID=$(python3 -c "import json,sys;print(json.load(open('$FILE'))['id'])")
  docker compose exec -T n8n n8n update:workflow --id="$WF_ID" --active=true >/dev/null 2>&1
  # Activation from the CLI only takes effect on restart; from the editor it is
  # immediate. Restarting here so the caller does not have to know that.
  docker compose restart n8n >/dev/null 2>&1
  echo "activated (n8n restarted - CLI activation does not take effect until then)"
fi
