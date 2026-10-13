# Lambda pulls only from private ECR.
resource "aws_ecr_repository" "this" {
  for_each = toset([local.orchestrator, local.scorer])

  name                 = each.key
  image_tag_mutability = "MUTABLE" # a re-run CI job can push the same SHA again

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "this" {
  for_each = aws_ecr_repository.this

  repository = each.value.name
  policy     = file("${local.policies_dir}/ecr-lifecycle.json")
}

# Declared rather than left to Lambda: without it, the first CreateFunction
# adds it through the caller's ecr:SetRepositoryPolicy, and CI's
# UpdateFunctionCode would depend on that having happened.
resource "aws_ecr_repository_policy" "lambda_pull" {
  for_each = aws_ecr_repository.this

  repository = each.value.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "LambdaPullFromThisFunctionOnly"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
      Condition = {
        StringLike = {
          "aws:sourceArn" = "arn:aws:lambda:${var.region}:${local.policy_vars.ACCOUNT_ID}:function:${each.key}"
        }
      }
    }]
  })
}
