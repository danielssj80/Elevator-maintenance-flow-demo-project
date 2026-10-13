locals {
  schedules = {
    "elevator-telemetry-ingest" = { expression = "rate(30 minutes)", workflow = "telemetry-ingest" }
    "elevator-daily-inference"  = { expression = "cron(0 6 * * ? *)", workflow = "daily-inference-and-digest" }
  }
}

resource "aws_scheduler_schedule" "this" {
  for_each = local.schedules

  name                         = each.key
  state                        = var.schedules_enabled ? "ENABLED" : "DISABLED"
  schedule_expression          = each.value.expression
  schedule_expression_timezone = "Europe/Madrid"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.orchestrator.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ workflow = each.value.workflow })

    # The scheduler's own retries; Lambda's are off in
    # aws_lambda_function_event_invoke_config.orchestrator.
    retry_policy {
      maximum_retry_attempts = 0
    }
  }
}
