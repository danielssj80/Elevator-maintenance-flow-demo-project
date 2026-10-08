#!/usr/bin/env bash
# Roles and customer-managed policies. Every document is in policies/ and is
# asserted for least privilege by backend/tests/unit/test_aws_policies.py.
# Usage: deploy/aws/20-iam.sh [--dry-run]
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh" "$@"

# Create or update a customer-managed policy from policies/<file>.
ensure_policy() {
  local name=$1 file=$2 arn="arn:aws:iam::${ACCOUNT_ID}:policy/$1" doc
  doc=$(render "$file")
  say "policy $name"
  if exists aws iam get-policy --policy-arn "$arn"; then
    # Five versions is IAM's limit: drop the oldest non-default one first.
    local oldest
    # Backticks are JMESPath literals, not command substitution.
    # shellcheck disable=SC2016
    oldest=$(aws iam list-policy-versions --policy-arn "$arn" \
      --query 'Versions[?IsDefaultVersion==`false`]|sort_by(@,&CreateDate)[0].VersionId' --output text)
    if [[ "$oldest" != "None" ]]; then
      run aws iam delete-policy-version --policy-arn "$arn" --version-id "$oldest"
    fi
    run aws iam create-policy-version --policy-arn "$arn" --policy-document "$doc" --set-as-default >/dev/null
  else
    run aws iam create-policy --policy-name "$name" --policy-document "$doc" >/dev/null
  fi
}

ensure_role() {
  local name=$1 trust=$2
  say "role $name"
  if ! exists aws iam get-role --role-name "$name"; then
    run aws iam create-role --role-name "$name" --assume-role-policy-document "$(render "$trust")" >/dev/null
  fi
}

attach() {
  run aws iam attach-role-policy --role-name "$1" --policy-arn "$2"
}

ensure_policy ElevatorOrchestratorFunction orchestrator-function.json
ensure_policy ElevatorScorerFunction scorer-function.json
ensure_policy ElevatorInvokeScorer instance-invoke-scorer.json
ensure_policy ElevatorHostReadSecrets host-read-secrets.json
ensure_policy ElevatorSchedulerInvoke scheduler-invoke.json
ensure_policy ElevatorLambdaImagesDeploy deploy-lambda-images.json

ensure_role "$ORCHESTRATOR_ROLE" lambda-trust.json
attach "$ORCHESTRATOR_ROLE" "arn:aws:iam::${ACCOUNT_ID}:policy/ElevatorOrchestratorFunction"
# The same pinned EU Nova Lite grant the backend's briefing already uses.
attach "$ORCHESTRATOR_ROLE" "$BEDROCK_POLICY_ARN"

ensure_role "$SCORER_ROLE" lambda-trust.json
attach "$SCORER_ROLE" "arn:aws:iam::${ACCOUNT_ID}:policy/ElevatorScorerFunction"

ensure_role "$SCHEDULER_ROLE" scheduler-trust.json
attach "$SCHEDULER_ROLE" "arn:aws:iam::${ACCOUNT_ID}:policy/ElevatorSchedulerInvoke"

say "existing roles"
attach "$INSTANCE_ROLE" "arn:aws:iam::${ACCOUNT_ID}:policy/ElevatorInvokeScorer"
attach "$INSTANCE_ROLE" "arn:aws:iam::${ACCOUNT_ID}:policy/ElevatorHostReadSecrets"
attach "$DEPLOY_ROLE" "arn:aws:iam::${ACCOUNT_ID}:policy/ElevatorLambdaImagesDeploy"
