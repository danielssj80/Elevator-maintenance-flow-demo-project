#!/usr/bin/env bash
# Export an n8n workflow to n8n/workflows/, scrubbed for publication.
#
# What it removes, and why each one matters:
#
#   credentials       - a credential block names the instance's credential ids.
#                       Publishing them leaks instance internals, and importing
#                       them elsewhere fails because those ids do not exist
#                       there. Removed entirely; the importer is told which
#                       credentials to attach by n8n/workflows/README.md.
#   meta.instanceId   - a stable fingerprint of the n8n instance.
#   versionId         - changes on every save, so leaving it in makes every
#                       export a diff even when nothing changed.
#   pinData           - captured sample data from editor runs. It routinely
#                       contains real API responses, and it silently overrides
#                       what a node fetches on import.
#   shared/ownership  - workspace and project ids from this instance.
#
# `id` is deliberately KEPT. n8n's import requires one (importing without it
# fails on a NOT NULL constraint), and ours are fixed literals chosen for this
# repository rather than instance-generated nanoids, so they carry nothing.
#
# python3, not jq: jq is not installed on the development machine and is not a
# project dependency, while python3 already is.
#
# Usage:  ./scripts/export-n8n-workflow.sh <workflow-id> [output-name]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

WORKFLOW_ID="${1:-}"
if [[ -z "$WORKFLOW_ID" ]]; then
  echo "Usage: $0 <workflow-id> [output-name]" >&2
  echo >&2
  echo "Workflows in the running instance:" >&2
  docker compose exec -T db psql -U user -d n8n -t -A -F' | ' \
    -c 'SELECT id, active, name FROM workflow_entity ORDER BY id;' >&2 || true
  exit 1
fi

OUT_DIR="$REPO_ROOT/n8n/workflows"
mkdir -p "$OUT_DIR"

# Passed through the environment, not a second heredoc: bash keeps only the
# last redirection, so `python3 - <<'PY' <<<"$RAW"` feeds python the JSON as
# its own source and dies on a syntax error in the Postgres banner.
export N8N_EXPORT_RAW
N8N_EXPORT_RAW=$(docker compose exec -T n8n n8n export:workflow --id="$WORKFLOW_ID" --pretty 2>/dev/null)

OUTPUT_NAME="${2:-}" python3 - "$OUT_DIR" <<'PY'
import json, os, re, sys, pathlib

out_dir = pathlib.Path(sys.argv[1])
raw = os.environ["N8N_EXPORT_RAW"]

# `n8n export:workflow` prints startup chatter before the JSON, so the document
# starts at the first bracket rather than at byte zero.
start = min((i for i in (raw.find("["), raw.find("{")) if i != -1), default=-1)
if start == -1:
    sys.exit("no JSON in the export output - is the n8n container running?")
data = json.loads(raw[start:])
workflows = data if isinstance(data, list) else [data]

STRIP_TOP = ("versionId", "meta", "pinData", "shared", "homeProject",
             "sharedWithProjects", "triggerCount", "createdAt", "updatedAt",
             "isArchived", "settings.callerPolicy")

for wf in workflows:
    for key in STRIP_TOP:
        wf.pop(key, None)
    # Never publish the active flag: whether a workflow runs is a property of
    # the instance it was imported into, not of the definition.
    wf["active"] = False
    for node in wf.get("nodes", []):
        node.pop("credentials", None)
        node.pop("webhookId", None)

    name = os.environ.get("OUTPUT_NAME") or re.sub(r"[^a-z0-9]+", "-", wf["name"].lower()).strip("-")
    path = out_dir / f"{name}.json"
    path.write_text(json.dumps(wf, indent=2, ensure_ascii=False) + "\n")

    leaked = [k for k in ("credentials", "instanceId", "versionId") if k in json.dumps(wf)]
    print(f"wrote {path.relative_to(pathlib.Path.cwd())}")
    print(f"  nodes: {len(wf.get('nodes', []))}")
    if leaked:
        sys.exit(f"  REFUSING: scrubbed export still mentions {leaked}")
    print("  scrubbed: no credentials, no instanceId, no versionId")
PY
