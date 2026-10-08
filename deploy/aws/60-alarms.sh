#!/usr/bin/env bash
# Alarms, sent by email through SNS:
#   - any error in either function (1 h);
#   - daily GB-s above 70 % of the free tier's daily pace (400,000 GB-s / 30);
#   - no successful daily run in 26 hours, or no successful ingest in 2 hours
#     (missing data = breaching, so a schedule that silently stops is an
#     alarm, not a quiet dashboard). These two notify only while the
#     schedules are enabled; see SILENCE_ALARMS in lib.sh.
#
# ALARM_EMAIL must be set on the first run; the subscription then has to be
# confirmed from the email AWS sends.
#
# Usage: ALARM_EMAIL=you@example.com deploy/aws/60-alarms.sh [--dry-run]
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh" "$@"

DAILY_GBS_THRESHOLD=9333   # 0.70 * 400000 / 30

say "SNS topic $ALARM_TOPIC"
if [[ "$DRY_RUN" == 1 ]]; then
  TOPIC_ARN="arn:aws:sns:${AWS_REGION}:${ACCOUNT_ID}:${ALARM_TOPIC}"
  run aws sns create-topic --name "$ALARM_TOPIC"
else
  TOPIC_ARN=$(aws sns create-topic --name "$ALARM_TOPIC" --query TopicArn --output text)  # idempotent
fi
if [[ -n "${ALARM_EMAIL:-}" ]]; then
  run aws sns subscribe --topic-arn "$TOPIC_ARN" --protocol email --notification-endpoint "$ALARM_EMAIL" >/dev/null
fi

for fn in "$ORCHESTRATOR" "$SCORER"; do
  say "alarm $fn-errors"
  run aws cloudwatch put-metric-alarm --alarm-name "$fn-errors" \
    --namespace AWS/Lambda --metric-name Errors --dimensions "Name=FunctionName,Value=$fn" \
    --statistic Sum --period 3600 --evaluation-periods 1 --threshold 0 \
    --comparison-operator GreaterThanThreshold --treat-missing-data notBreaching \
    --alarm-actions "$TOPIC_ARN"
done

say "alarm elevator-lambda-daily-gbs"
# Lambda publishes no GB-s metric: Duration (ms) x configured memory (GB).
# Keep the two memory sizes here in step with 40-lambda.sh.
METRICS=$(cat <<JSON
[
  {"Id": "orch", "ReturnData": false, "MetricStat": {"Metric": {"Namespace": "AWS/Lambda", "MetricName": "Duration",
    "Dimensions": [{"Name": "FunctionName", "Value": "$ORCHESTRATOR"}]}, "Period": 86400, "Stat": "Sum"}},
  {"Id": "scorer", "ReturnData": false, "MetricStat": {"Metric": {"Namespace": "AWS/Lambda", "MetricName": "Duration",
    "Dimensions": [{"Name": "FunctionName", "Value": "$SCORER"}]}, "Period": 86400, "Stat": "Sum"}},
  {"Id": "gbs", "ReturnData": true, "Label": "GB-seconds per day",
    "Expression": "(FILL(orch,0) * $ORCHESTRATOR_MEMORY_MB + FILL(scorer,0) * $SCORER_MEMORY_MB) / 1024 / 1000"}
]
JSON
)
run aws cloudwatch put-metric-alarm --alarm-name elevator-lambda-daily-gbs \
  --metrics "$METRICS" --evaluation-periods 1 --threshold "$DAILY_GBS_THRESHOLD" \
  --comparison-operator GreaterThanThreshold --treat-missing-data notBreaching \
  --alarm-actions "$TOPIC_ARN"

# Silence alarms carry actions only while scheduled work is switched on.
SILENCE_ACTIONS=--no-actions-enabled
if [[ "$DRY_RUN" == 0 ]] && [[ "$(aws scheduler get-schedule --name "$INGEST_SCHEDULE" \
     --query State --output text 2>/dev/null || true)" == ENABLED ]]; then
  SILENCE_ACTIONS=--actions-enabled
fi

# WorkflowSucceeded is emitted by the orchestrator handler (EMF), per workflow:
# Invocations alone would stay above zero on ingest runs forever.
# 26 x 1 h = 93,600 s of evaluation: PutMetricAlarm allows up to 7 days for
# periods of an hour or more (verified at provisioning; the call fails loudly
# otherwise).
say "alarm elevator-daily-run-missing"
run aws cloudwatch put-metric-alarm --alarm-name elevator-daily-run-missing \
  --namespace Elevator/Orchestrator --metric-name WorkflowSucceeded \
  --dimensions Name=Workflow,Value=daily-inference-and-digest \
  --statistic Sum --period 3600 --evaluation-periods 26 --datapoints-to-alarm 26 \
  --threshold 1 --comparison-operator LessThanThreshold --treat-missing-data breaching \
  --alarm-actions "$TOPIC_ARN" "$SILENCE_ACTIONS"

say "alarm elevator-ingest-missing"
run aws cloudwatch put-metric-alarm --alarm-name elevator-ingest-missing \
  --namespace Elevator/Orchestrator --metric-name WorkflowSucceeded \
  --dimensions Name=Workflow,Value=telemetry-ingest \
  --statistic Sum --period 3600 --evaluation-periods 2 --datapoints-to-alarm 2 \
  --threshold 1 --comparison-operator LessThanThreshold --treat-missing-data breaching \
  --alarm-actions "$TOPIC_ARN" "$SILENCE_ACTIONS"
