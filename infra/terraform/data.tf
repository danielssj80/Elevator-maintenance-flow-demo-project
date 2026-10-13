data "aws_caller_identity" "current" {}

# Existing resources: read, never managed here. Policies are only attached to
# the two roles (aws_iam_role_policy_attachment), which leaves the roles alone.
data "aws_iam_role" "instance" {
  name = var.instance_role_name
}

data "aws_iam_role" "deploy" {
  name = var.deploy_role_name
}

data "aws_iam_policy" "bedrock" {
  name = var.bedrock_policy_name
}

locals {
  # The JSON documents under deploy/aws/policies/ are the single source, and
  # backend/tests/unit/test_aws_policies.py asserts them for least privilege.
  policies_dir = "${path.module}/../../deploy/aws/policies"
  policy_vars = {
    ACCOUNT_ID = data.aws_caller_identity.current.account_id
    AWS_REGION = var.region
  }

  orchestrator = "elevator-orchestrator"
  scorer       = "elevator-scorer"

  # SSM parameters: created by deploy/aws/30-ssm.sh, never by Terraform (the
  # provider would refresh their decrypted values into the state).
  param_ingest_token  = "/elevator/orchestrator/ingest-token"
  param_otel_endpoint = "/elevator/otel/grafana-otlp-endpoint"
  param_otel_auth     = "/elevator/otel/grafana-otlp-auth"
}
