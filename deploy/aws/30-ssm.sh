#!/usr/bin/env bash
# The production secrets, as SecureString parameters. Never printed.
#
#   ingest token   generated here (>= 32 chars) if absent; kept on re-runs.
#                  --rotate replaces it (then run 70-host-env.sh).
#   Grafana Cloud  OTLP endpoint and "Authorization=Basic ..." header, read
#                  from the prompt (silent) if absent; --reset-otel re-asks.
#
# Usage: deploy/aws/30-ssm.sh [--dry-run] [--rotate] [--reset-otel]
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh" "$@"

ROTATE=0; RESET_OTEL=0
for arg in "$@"; do
  [[ "$arg" == "--rotate" ]] && ROTATE=1
  [[ "$arg" == "--reset-otel" ]] && RESET_OTEL=1
done

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
  if [[ "$DRY_RUN" == 1 ]]; then
    put_secret "$name" "dry-run" "$([[ "$RESET_OTEL" == 1 ]] && echo true || echo false)"
    continue
  fi
  read -r -s -p "$prompt: " value; echo
  [[ -n "$value" ]] || { echo "empty value; not stored" >&2; exit 1; }
  overwrite=false; [[ "$RESET_OTEL" == 1 ]] && overwrite=true
  put_secret "$name" "$value" "$overwrite"
done
