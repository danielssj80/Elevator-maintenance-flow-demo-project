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

# n8n 2.x does not emit `versionId` at all; it emits `activeVersionId`, a
# per-instance UUID, plus `versionCounter` and `versionMetadata`. The first
# version of this script stripped the key that no longer exists and left the one
# that does, then reported "no versionId" — truthfully and uselessly, because
# the leak check was a case-sensitive substring and `activeVersionId` does not
# contain `versionId`.
STRIP_TOP = ("versionId", "activeVersionId", "versionCounter", "versionMetadata",
             "meta", "pinData", "shared", "homeProject", "sharedWithProjects",
             "triggerCount", "createdAt", "updatedAt", "isArchived")

# Node parameter values that carry a secret when someone types a header by hand
# instead of attaching a credential — which is what the n8n UI produces, and
# which the credential-block scrub does not touch because there is no credential
# block to remove.
SECRET_HEADER_NAMES = {"authorization", "x-ingest-token", "x-api-key", "apikey",
                       "api-key", "token", "cookie", "proxy-authorization"}
SECRET_VALUE_HINTS = ("bearer ", "sk-", "akia", "asia", "glc_", "ghp_", "xoxb-")


def _secret_findings(node):
    """Header and query parameter values that must never be published."""
    found = []
    params = node.get("parameters", {}) or {}
    for group in ("headerParameters", "queryParameters", "bodyParameters"):
        for entry in (params.get(group, {}) or {}).get("parameters", []) or []:
            name = str(entry.get("name", "")).strip().lower()
            value = str(entry.get("value", "")).strip()
            if not value or value.startswith("="):
                continue  # an expression, not a literal
            if name in SECRET_HEADER_NAMES:
                found.append(f"{node.get('name')}: {group}.{entry.get('name')}")
            elif any(h in value.lower() for h in SECRET_VALUE_HINTS):
                found.append(f"{node.get('name')}: {group}.{entry.get('name')} (looks like a token)")
    return found

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

    # CHECK BEFORE WRITING. The first version wrote the file and then exited on a
    # leak, which left the leaked artefact on disk, ready for `git add` — a guard
    # that announces a refusal and publishes the thing anyway.
    rendered = json.dumps(wf, indent=2, ensure_ascii=False) + "\n"

    # Key-name check, case-insensitively this time.
    lowered = rendered.lower()
    leaked = [k for k in ("credentials", "instanceid", "versionid", "versioncounter")
              if k in lowered]
    # Value check. Key names alone pass a real secret straight through: an inline
    # `Authorization: Bearer sk-...` header has no credential block to strip.
    for node in wf.get("nodes", []):
        leaked.extend(_secret_findings(node))

    print(f"would write {path.relative_to(pathlib.Path.cwd())}")
    print(f"  nodes: {len(wf.get('nodes', []))}")
    if leaked:
        sys.exit(
            f"  REFUSING, and NOT writing: the scrubbed export still carries {leaked}. "
            "Use an n8n credential instead of an inline header, or extend the scrubber."
        )

    path.write_text(rendered)
    print(f"  wrote {path.relative_to(pathlib.Path.cwd())}")
    print("  scrubbed: no credentials, no instance or version ids, no inline secrets")
PY
