resource "aws_sns_topic" "alarms" {
  name = "elevator-alarms"
}

resource "aws_sns_topic_subscription" "email" {
  count = var.alarm_email == "" ? 0 : 1

  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

# Any function error in an hour. Missing data = not breaching: no runs, no
# errors. Silence is the silence alarms' job.
resource "aws_cloudwatch_metric_alarm" "errors" {
  for_each = toset([local.orchestrator, local.scorer])

  alarm_name          = "${each.key}-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = each.key }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

# Lambda publishes no GB-s metric: Duration (ms) x configured memory (GB).
# 70 % of the free tier's daily pace: 0.70 * 400,000 / 30 ≈ 9,333 GB-s.
resource "aws_cloudwatch_metric_alarm" "daily_gbs" {
  alarm_name          = "elevator-lambda-daily-gbs"
  evaluation_periods  = 1
  threshold           = 9333
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]

  metric_query {
    id = "orch"
    metric {
      namespace   = "AWS/Lambda"
      metric_name = "Duration"
      dimensions  = { FunctionName = local.orchestrator }
      period      = 86400
      stat        = "Sum"
    }
  }

  metric_query {
    id = "scorer"
    metric {
      namespace   = "AWS/Lambda"
      metric_name = "Duration"
      dimensions  = { FunctionName = local.scorer }
      period      = 86400
      stat        = "Sum"
    }
  }

  metric_query {
    id          = "gbs"
    label       = "GB-seconds per day"
    return_data = true
    expression  = "(FILL(orch,0) * ${aws_lambda_function.orchestrator.memory_size} + FILL(scorer,0) * ${aws_lambda_function.scorer.memory_size}) / 1024 / 1000"
  }
}

# Scheduled work that went silent. WorkflowSucceeded is emitted per workflow by
# the orchestrator handler (EMF): Invocations alone would stay above zero on
# ingest runs forever. Missing data = breaching. Notify only while scheduled.
locals {
  silence_alarms = {
    "elevator-daily-run-missing" = { workflow = "daily-inference-and-digest", periods = 26 }
    "elevator-ingest-missing"    = { workflow = "telemetry-ingest", periods = 2 }
  }
}

resource "aws_cloudwatch_metric_alarm" "silence" {
  for_each = local.silence_alarms

  alarm_name          = each.key
  namespace           = "Elevator/Orchestrator"
  metric_name         = "WorkflowSucceeded"
  dimensions          = { Workflow = each.value.workflow }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = each.value.periods
  datapoints_to_alarm = each.value.periods
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  actions_enabled     = var.schedules_enabled
  alarm_actions       = [aws_sns_topic.alarms.arn]
}
