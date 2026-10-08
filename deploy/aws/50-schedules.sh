#!/usr/bin/env bash
# EventBridge Scheduler: ingest every 30 minutes, inference and digest daily at
# 06:00 Europe/Madrid. No retries: a retried re-score would hide the failure
# the error alarm exists to report.
#
# Created DISABLED. Turning production's scheduled work on (or off) is its own
# step: --enable / --disable.
#
# Usage: deploy/aws/50-schedules.sh [--dry-run] [--enable | --disable]
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh" "$@"

STATE=""
for arg in "$@"; do
  [[ "$arg" == "--enable" ]] && STATE=ENABLED
  [[ "$arg" == "--disable" ]] && STATE=DISABLED
done

FUNCTION_ARN="arn:aws:lambda:${AWS_REGION}:${ACCOUNT_ID}:function:${ORCHESTRATOR}"
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${SCHEDULER_ROLE}"

ensure_schedule() {
  local name=$1 expression=$2 workflow=$3 state current
  say "schedule $name"
  local target="{\"Arn\":\"$FUNCTION_ARN\",\"RoleArn\":\"$ROLE_ARN\",\"Input\":\"{\\\"workflow\\\":\\\"$workflow\\\"}\",\"RetryPolicy\":{\"MaximumRetryAttempts\":0}}"
  if exists aws scheduler get-schedule --name "$name"; then
    current=$(aws scheduler get-schedule --name "$name" --query State --output text)
    state=${STATE:-$current}
    run aws scheduler update-schedule --name "$name" --schedule-expression "$expression" \
      --schedule-expression-timezone Europe/Madrid --flexible-time-window Mode=OFF \
      --target "$target" --state "$state" >/dev/null
  else
    state=${STATE:-DISABLED}
    run aws scheduler create-schedule --name "$name" --schedule-expression "$expression" \
      --schedule-expression-timezone Europe/Madrid --flexible-time-window Mode=OFF \
      --target "$target" --state "$state" >/dev/null
  fi
  echo "   state: $state"
}

ensure_schedule elevator-telemetry-ingest "rate(30 minutes)" telemetry-ingest
ensure_schedule elevator-daily-inference "cron(0 6 * * ? *)" daily-inference-and-digest
