#!/usr/bin/env bash
# Write the production host's secrets into /etc/elevator/.env from SSM, then
# recreate the backend so it reads them. Runs ON the instance through SSM Run
# Command: the values travel from SSM to the host with the instance role and
# never pass through this machine, a command parameter or a log.
#
#   TELEMETRY_INGEST_TOKEN       same value the orchestrator sends
#   OTEL_EXPORTER_OTLP_ENDPOINT  Grafana Cloud
#   OTEL_EXPORTER_OTLP_HEADERS   stored in SSM with a literal space ("Basic x"),
#                                which n8n needs; written here URL-encoded
#                                ("Basic%20x"), which the Python SDK expects.
#
# Usage: deploy/aws/70-host-env.sh [--dry-run]
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh" "$@"

# Literal on purpose: expanded on the instance, not here.
# shellcheck disable=SC2016
COMMANDS=$(python3 - "$AWS_REGION" "$PARAM_INGEST_TOKEN" "$PARAM_OTEL_ENDPOINT" "$PARAM_OTEL_AUTH" <<'PY'
import json, sys
region, token, endpoint, auth = sys.argv[1:]
script = [
    "set -eu",
    "umask 077",
    "F=/etc/elevator/.env",
    f"get() {{ aws ssm get-parameter --region {region} --name \"$1\" --with-decryption --query Parameter.Value --output text; }}",
    "put() { grep -v \"^$1=\" \"$F\" > \"$F.new\" || true; printf '%s=%s\\n' \"$1\" \"$2\" >> \"$F.new\"; chmod --reference=\"$F\" \"$F.new\"; mv \"$F.new\" \"$F\"; }",
    # Assignments, not "$(get ...)" as an argument: set -e does not see a
    # failure inside an argument, and an empty token would be written.
    f"token=$(get {token}); endpoint=$(get {endpoint}); auth=$(get {auth})",
    "[ -n \"$token\" ] && [ -n \"$endpoint\" ] && [ -n \"$auth\" ]",
    "put TELEMETRY_INGEST_TOKEN \"$token\"",
    "put OTEL_EXPORTER_OTLP_ENDPOINT \"$endpoint\"",
    "put OTEL_EXPORTER_OTLP_HEADERS \"$(printf '%s' \"$auth\" | sed 's/ /%20/g')\"",
    "cd /opt/elevator",
    # The image of the deployed commit, as deploy.yml runs it; unset, compose
    # would fall back to :latest.
    "export IMAGE_TAG=$(git rev-parse HEAD)",
    "flock -w 600 /opt/deploy.lock docker compose -f docker-compose.prod.yml up -d --no-deps backend",
    "echo written: $(grep -c -E '^(TELEMETRY_INGEST_TOKEN|OTEL_EXPORTER_OTLP_ENDPOINT|OTEL_EXPORTER_OTLP_HEADERS)=' \"$F\") of 3",
]
print(json.dumps({"commands": script, "executionTimeout": ["600"]}))
PY
)

say "host env on $INSTANCE_ID"
if [[ "$DRY_RUN" == 1 ]]; then
  echo "+ aws ssm send-command --instance-ids $INSTANCE_ID --document-name AWS-RunShellScript --parameters <commands below>"
  python3 -c 'import json,sys;[print("    " + c) for c in json.loads(sys.argv[1])["commands"]]' "$COMMANDS"
  exit 0
fi

COMMAND_ID=$(aws ssm send-command --instance-ids "$INSTANCE_ID" --document-name AWS-RunShellScript \
  --comment "Write host env from SSM" --parameters "$COMMANDS" --query Command.CommandId --output text)
aws ssm wait command-executed --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" || true
aws ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" \
  --query '{status: Status, out: StandardOutputContent, err: StandardErrorContent}' --output json
