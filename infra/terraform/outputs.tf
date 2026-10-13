output "repository_urls" {
  value = { for name, repo in aws_ecr_repository.this : name => repo.repository_url }
}

output "functions" {
  value = [aws_lambda_function.orchestrator.function_name, aws_lambda_function.scorer.function_name]
}

output "schedules_state" {
  value = { for name, s in aws_scheduler_schedule.this : name => s.state }
}

output "alarm_topic_arn" {
  value = aws_sns_topic.alarms.arn
}
