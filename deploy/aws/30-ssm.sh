#!/usr/bin/env bash
# The production secrets, as SecureString parameters. Never printed.
#
#   ingest token   generated here (>= 32 chars) if absent; kept on re-runs.
#                  --rotate replaces it (then run 70-host-env.sh).
#   Grafana Cloud  OTLP endpoint and "Authorization=Basic ..." header, read
#                  from the prompt (silent) if absent; --reset-otel re-asks.
#                  --from-dotenv builds both from the local stack's .env
#                  (GRAFANA_CLOUD_OTLP_ENDPOINT, _INSTANCE_ID, _API_TOKEN)
#                  instead, checks them against Grafana Cloud, prints nothing.
#
# Usage: deploy/aws/30-ssm.sh [--dry-run] [--rotate] [--reset-otel] [--from-dotenv]
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh" "$@"

ROTATE=0; RESET_OTEL=0; FROM_DOTENV=0
for arg in "$@"; do
  [[ "$arg" == "--rotate" ]] && ROTATE=1
  [[ "$arg" == "--reset-otel" ]] && RESET_OTEL=1
  [[ "$arg" == "--from-dotenv" ]] && FROM_DOTENV=1
done

# Endpoint and header from the git-ignored root .env, verified before use.
# A Basic header Grafana answers 401/403 to is refused, so a stale token is
# found here rather than as traces that silently never arrive.
DOTENV_ENDPOINT=""; DOTENV_HEADER=""
if [[ "$FROM_DOTENV" == 1 && "$DRY_RUN" == 0 ]]; then
  dotenv="$HERE/../../.env"
  [[ -f "$dotenv" ]] || { echo "no .env at the repository root" >&2; exit 1; }
  read_env() { grep -E "^$1=" "$dotenv" | tail -1 | cut -d= -f2- | sed -e 's/^["'\'']//' -e 's/["'\'']$//'; }
  DOTENV_ENDPOINT=$(read_env GRAFANA_CLOUD_OTLP_ENDPOINT)
  instance=$(read_env GRAFANA_CLOUD_INSTANCE_ID)
  token=$(read_env GRAFANA_CLOUD_API_TOKEN)
  [[ -n "$DOTENV_ENDPOINT" && -n "$instance" && -n "$token" ]] || {
    echo ".env lacks GRAFANA_CLOUD_OTLP_ENDPOINT, _INSTANCE_ID or _API_TOKEN" >&2; exit 1; }
  DOTENV_HEADER="Authorization=Basic $(printf '%s:%s' "$instance" "$token" | base64 -w0)"
  unset token
  # The header goes to curl on stdin, not argv, so no process list shows it.
  status=$(printf 'header = "Authorization: %s"\n' "${DOTENV_HEADER#Authorization=}" |
    curl -s -o /dev/null -w '%{http_code}' --config - -X POST \
      -H 'Content-Type: application/x-protobuf' --data-binary '' "${DOTENV_ENDPOINT%/}/v1/traces")
  if [[ "$status" == 401 || "$status" == 403 || "$status" == 000 ]]; then
    echo "Grafana Cloud refused the .env credentials (HTTP $status); not stored" >&2
    exit 1
  fi
  echo "   Grafana Cloud accepted the .env credentials (HTTP $status)" >&2
  RESET_OTEL=1
fi

# put-parameter from a 0600 file, so a value never appears in a process list.
# overwrite=false creates only: an existing parameter is kept, and only
# ParameterAlreadyExists counts as "kept" — any other error (throttling,
# access) stops the script instead of being mistaken for "absent" and
# silently rotating the token.
put_secret() {
  local name=$1 value=$2 overwrite=$3 tmp err
  if [[ "$DRY_RUN" == 1 ]]; then
    printf '+ aws ssm put-parameter --name %s --type SecureString --overwrite=%s --value <redacted>\n' "$name" "$overwrite" >&2
    return
  fi
  tmp=$(umask 077; mktemp)
  NAME="$name" VALUE="$value" OVERWRITE="$overwrite" python3 -c \
    'import json,os;print(json.dumps({"Name":os.environ["NAME"],"Value":os.environ["VALUE"],"Type":"SecureString","Overwrite":os.environ["OVERWRITE"]=="true"}))' >"$tmp"
  if ! err=$(aws ssm put-parameter --cli-input-json "file://$tmp" 2>&1 >/dev/null); then
    rm -f "$tmp"
    if [[ "$overwrite" == false && "$err" == *ParameterAlreadyExists* ]]; then
      echo "   exists; kept" >&2
      return
    fi
    echo "$err" >&2
    return 1
  fi
  rm -f "$tmp"
  echo "   stored" >&2
}

say "$PARAM_INGEST_TOKEN"
TOKEN_OVERWRITE=false; [[ "$ROTATE" == 1 ]] && TOKEN_OVERWRITE=true
put_secret "$PARAM_INGEST_TOKEN" "$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')" "$TOKEN_OVERWRITE"

for pair in "$PARAM_OTEL_ENDPOINT:Grafana Cloud OTLP endpoint (https://otlp-gateway-...grafana.net/otlp)" \
            "$PARAM_OTEL_AUTH:Grafana Cloud OTLP header (Authorization=Basic <base64>)"; do
  name=${pair%%:*}; prompt=${pair#*:}
  say "$name"
  if [[ "$RESET_OTEL" == 0 ]] && [[ "$DRY_RUN" == 0 ]] && \
     aws ssm get-parameter --name "$name" --query Parameter.Name --output text >/dev/null 2>&1; then
    echo "   exists; kept (--reset-otel to replace)" >&2
    continue
  fi
  if [[ "$FROM_DOTENV" == 1 && "$DRY_RUN" == 0 ]]; then
    value=$DOTENV_ENDPOINT; [[ "$name" == "$PARAM_OTEL_AUTH" ]] && value=$DOTENV_HEADER
    put_secret "$name" "$value" true
    continue
  fi
  if [[ "$DRY_RUN" == 1 ]]; then
    put_secret "$name" "dry-run" "$([[ "$RESET_OTEL" == 1 ]] && echo true || echo false)"
    continue
  fi
  if [[ ! -t 0 ]]; then
    # `read -s` needs a terminal; without one it hits EOF and set -e ends the
    # script with no message. Say what to do instead.
    echo "$name needs a value typed at a terminal; run this script in an interactive shell" >&2
    exit 1
  fi
  read -r -s -p "$prompt: " value; echo
  [[ -n "$value" ]] || { echo "empty value; not stored" >&2; exit 1; }
  overwrite=false; [[ "$RESET_OTEL" == 1 ]] && overwrite=true
  put_secret "$name" "$value" "$overwrite"
done
