resource "aws_iam_policy" "this" {
  for_each = {
    ElevatorOrchestratorFunction = "orchestrator-function.json"
    ElevatorScorerFunction       = "scorer-function.json"
    ElevatorInvokeScorer         = "instance-invoke-scorer.json"
    ElevatorHostReadSecrets      = "host-read-secrets.json"
    ElevatorSchedulerInvoke      = "scheduler-invoke.json"
    ElevatorLambdaImagesDeploy   = "deploy-lambda-images.json"
  }

  name   = each.key
  policy = templatefile("${local.policies_dir}/${each.value}", local.policy_vars)
}

resource "aws_iam_role" "orchestrator" {
  name               = "elevator-orchestrator-function"
  assume_role_policy = templatefile("${local.policies_dir}/lambda-trust.json", local.policy_vars)
}

resource "aws_iam_role" "scorer" {
  name               = "elevator-scorer-function"
  assume_role_policy = templatefile("${local.policies_dir}/lambda-trust.json", local.policy_vars)
}

resource "aws_iam_role" "scheduler" {
  name               = "elevator-scheduler-invoke"
  assume_role_policy = templatefile("${local.policies_dir}/scheduler-trust.json", local.policy_vars)
}

locals {
  attachments = {
    orchestrator_own     = { role = aws_iam_role.orchestrator.name, policy = aws_iam_policy.this["ElevatorOrchestratorFunction"].arn }
    orchestrator_bedrock = { role = aws_iam_role.orchestrator.name, policy = data.aws_iam_policy.bedrock.arn }
    scorer_own           = { role = aws_iam_role.scorer.name, policy = aws_iam_policy.this["ElevatorScorerFunction"].arn }
    scheduler_invoke     = { role = aws_iam_role.scheduler.name, policy = aws_iam_policy.this["ElevatorSchedulerInvoke"].arn }
    # Existing roles: attach only.
    instance_scorer  = { role = data.aws_iam_role.instance.name, policy = aws_iam_policy.this["ElevatorInvokeScorer"].arn }
    instance_secrets = { role = data.aws_iam_role.instance.name, policy = aws_iam_policy.this["ElevatorHostReadSecrets"].arn }
    deploy_images    = { role = data.aws_iam_role.deploy.name, policy = aws_iam_policy.this["ElevatorLambdaImagesDeploy"].arn }
  }
}

resource "aws_iam_role_policy_attachment" "this" {
  for_each = local.attachments

  role       = each.value.role
  policy_arn = each.value.policy
}
