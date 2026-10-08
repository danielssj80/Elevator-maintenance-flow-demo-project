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
put_secret() {
  local name=$1 value=$2 tmp
  if [[ "$DRY_RUN" == 1 ]]; then
    printf '+ aws ssm put-parameter --name %s --type SecureString --overwrite --value <redacted>\n' "$name"
    return
  fi
  tmp=$(umask 077; mktemp)
  trap 'rm -f "$tmp"' RETURN
  NAME="$name" VALUE="$value" python3 -c \
    'import json,os;print(json.dumps({"Name":os.environ["NAME"],"Value":os.environ["VALUE"],"Type":"SecureString","Overwrite":True}))' >"$tmp"
  aws ssm put-parameter --cli-input-json "file://$tmp" >/dev/null
}

say "$PARAM_INGEST_TOKEN"
if [[ "$ROTATE" == 1 ]] || ! exists aws ssm get-parameter --name "$PARAM_INGEST_TOKEN"; then
  put_secret "$PARAM_INGEST_TOKEN" "$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')"
fi

for pair in "$PARAM_OTEL_ENDPOINT:Grafana Cloud OTLP endpoint (https://otlp-gateway-...grafana.net/otlp)" \
            "$PARAM_OTEL_AUTH:Grafana Cloud OTLP header (Authorization=Basic <base64>)"; do
  name=${pair%%:*}; prompt=${pair#*:}
  say "$name"
  if [[ "$RESET_OTEL" == 1 ]] || ! exists aws ssm get-parameter --name "$name"; then
    if [[ "$DRY_RUN" == 1 ]]; then
      put_secret "$name" "dry-run"
    else
      read -r -s -p "$prompt: " value; echo
      [[ -n "$value" ]] || { echo "empty value; not stored" >&2; exit 1; }
      put_secret "$name" "$value"
    fi
  fi
done
