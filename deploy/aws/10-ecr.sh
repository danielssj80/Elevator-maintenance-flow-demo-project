#!/usr/bin/env bash
# Private ECR repositories for the two Lambda images (Lambda pulls from nowhere
# else), each keeping its three most recent images.
# Usage: deploy/aws/10-ecr.sh [--dry-run]
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh" "$@"

for repo in "$ORCHESTRATOR" "$SCORER"; do
  say "ECR repository $repo"
  if ! exists aws ecr describe-repositories --repository-names "$repo"; then
    run aws ecr create-repository --repository-name "$repo" \
      --image-scanning-configuration scanOnPush=true --image-tag-mutability MUTABLE >/dev/null
  fi
  run aws ecr put-lifecycle-policy --repository-name "$repo" \
    --lifecycle-policy-text "file://$HERE/policies/ecr-lifecycle.json" >/dev/null
done
