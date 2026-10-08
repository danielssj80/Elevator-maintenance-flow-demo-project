# shellcheck shell=bash
# shellcheck disable=SC2034  # read by the scripts that source this file
# Shared by every deploy/aws script: names, the dry-run switch, and helpers.
# Sourced, never executed.
#
# Every script is safe to re-run: it describes before it creates, and updates
# in place what already exists. `--dry-run` prints each AWS call instead of
# making it and treats every resource as absent, so the creation path is what
# gets printed.

set -euo pipefail

DRY_RUN=0
for arg in "$@"; do
  [[ "$arg" == "--dry-run" ]] && DRY_RUN=1
done

AWS_REGION="${AWS_REGION:-eu-north-1}"
export AWS_REGION AWS_DEFAULT_REGION="$AWS_REGION"

if [[ "$DRY_RUN" == 1 ]]; then
  ACCOUNT_ID="${ACCOUNT_ID:-123456789012}"
else
  ACCOUNT_ID="${ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text)}"
fi

INSTANCE_ID="${INSTANCE_ID:-i-01b732fefb1dd6303}"
INSTANCE_ROLE="${INSTANCE_ROLE:-elevator-ssm-role}"
DEPLOY_ROLE="${DEPLOY_ROLE:-github-actions-deploy}"
BEDROCK_POLICY_ARN="arn:aws:iam::${ACCOUNT_ID}:policy/ElevatorBedrockInvokeNova"

ORCHESTRATOR=elevator-orchestrator
SCORER=elevator-scorer
ORCHESTRATOR_ROLE=elevator-orchestrator-function
SCORER_ROLE=elevator-scorer-function
SCHEDULER_ROLE=elevator-scheduler-invoke
REGISTRY="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

PARAM_INGEST_TOKEN=/elevator/orchestrator/ingest-token
PARAM_OTEL_ENDPOINT=/elevator/otel/grafana-otlp-endpoint
PARAM_OTEL_AUTH=/elevator/otel/grafana-otlp-auth

ORCHESTRATOR_MEMORY_MB=2048
ORCHESTRATOR_TIMEOUT_S=120
SCORER_MEMORY_MB=1024
SCORER_TIMEOUT_S=30
ALARM_TOPIC=elevator-alarms

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Run a mutating AWS call, or print it. Printed to stderr: callers silence the
# call's JSON output with >/dev/null, which must not silence the dry run.
run() {
  if [[ "$DRY_RUN" == 1 ]]; then
    { printf '+'; printf ' %q' "$@"; printf '\n'; } >&2
  else
    "$@"
  fi
}

# True when the describe call succeeds. Always false in a dry run.
exists() {
  if [[ "$DRY_RUN" == 1 ]]; then
    printf '? %s\n' "$*" >&2
    return 1
  fi
  "$@" >/dev/null 2>&1
}

# A policy document with ACCOUNT_ID / AWS_REGION substituted.
render() {
  sed -e "s/\${ACCOUNT_ID}/${ACCOUNT_ID}/g" -e "s/\${AWS_REGION}/${AWS_REGION}/g" "$HERE/policies/$1"
}

say() { printf '== %s\n' "$*"; }
