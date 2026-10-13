# shellcheck shell=bash
# shellcheck disable=SC2034  # read by the scripts that source this file
# Shared by the deploy/aws scripts: names, the dry-run switch, and helpers.
# Sourced, never executed.
#
# AWS resources are Terraform's (infra/terraform/). What stays here is what
# must not pass through the Terraform state: secret values (30-ssm.sh), the
# host env file (70-host-env.sh), and the one-off bootstrap image push.

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

ORCHESTRATOR=elevator-orchestrator
SCORER=elevator-scorer
REGISTRY="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

# Created by 30-ssm.sh, never by Terraform (infra/terraform/data.tf explains).
PARAM_INGEST_TOKEN=/elevator/orchestrator/ingest-token
PARAM_OTEL_ENDPOINT=/elevator/otel/grafana-otlp-endpoint
PARAM_OTEL_AUTH=/elevator/otel/grafana-otlp-auth

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

say() { printf '== %s\n' "$*"; }
