# Created before the functions so their retention is ours, not "never expire".
resource "aws_cloudwatch_log_group" "function" {
  for_each = toset([local.orchestrator, local.scorer])

  name              = "/aws/lambda/${each.key}"
  retention_in_days = 14
}

resource "aws_lambda_function" "orchestrator" {
  function_name = local.orchestrator
  role          = aws_iam_role.orchestrator.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.this[local.orchestrator].repository_url}:${var.image_tag}"
  architectures = ["x86_64"]
  memory_size   = 2048 # 16–28 s per run measured; 1024 MB doubles duration, 512 MB fails
  timeout       = 120

  reserved_concurrent_executions = var.reserve_orchestrator_concurrency ? 1 : -1

  environment {
    # SSM parameter NAMES; the handler reads the values with this role.
    variables = {
      INGEST_TOKEN_PARAMETER  = local.param_ingest_token
      OTEL_ENDPOINT_PARAMETER = local.param_otel_endpoint
      OTEL_HEADERS_PARAMETER  = local.param_otel_auth
    }
  }

  lifecycle {
    # CI (lambda-images.yml) moves the image on every merge.
    ignore_changes = [image_uri]
  }

  depends_on = [
    aws_cloudwatch_log_group.function,
    aws_iam_role_policy_attachment.this,
    aws_ecr_repository_policy.lambda_pull,
  ]
}

# EventBridge Scheduler invokes asynchronously, so Lambda's own retry policy
# (default: 2 retries, events kept 6 h) would apply on top of the schedule's.
# A retried re-score runs again; a retried ingest stores new readings.
resource "aws_lambda_function_event_invoke_config" "orchestrator" {
  function_name                = aws_lambda_function.orchestrator.function_name
  maximum_retry_attempts       = 0
  maximum_event_age_in_seconds = 900
}

resource "aws_lambda_function" "scorer" {
  function_name = local.scorer
  role          = aws_iam_role.scorer.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.this[local.scorer].repository_url}:${var.image_tag}"
  architectures = ["x86_64"]
  memory_size   = 1024 # ~150 MiB peak; cold start ~2 s
  timeout       = 30

  environment {
    variables = {
      OTEL_ENABLED            = "true"
      OTEL_SERVICE_NAME       = local.scorer
      OTEL_ENDPOINT_PARAMETER = local.param_otel_endpoint
      OTEL_HEADERS_PARAMETER  = local.param_otel_auth
      DEPLOYMENT_ENVIRONMENT  = "production"
    }
  }

  lifecycle {
    ignore_changes = [image_uri]
  }

  depends_on = [
    aws_cloudwatch_log_group.function,
    aws_iam_role_policy_attachment.this,
    aws_ecr_repository_policy.lambda_pull,
  ]
}
