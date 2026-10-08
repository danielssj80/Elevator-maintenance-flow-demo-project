#!/usr/bin/env bash
# The two functions. CI moves their code on every merge (lambda-images.yml);
# this script creates them and owns their configuration.
#
# A function can only be created from an image that is already in ECR, so on
# the very first run pass --bootstrap-image: it builds both images locally and
# pushes them tagged with the current commit.
#
# Usage: deploy/aws/40-lambda.sh [--dry-run] [--bootstrap-image]
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh" "$@"

BOOTSTRAP=0
for arg in "$@"; do [[ "$arg" == "--bootstrap-image" ]] && BOOTSTRAP=1; done

REPO_ROOT="$(cd "$HERE/../.." && pwd)"
TAG="$(git -C "$REPO_ROOT" rev-parse HEAD)"

if [[ "$BOOTSTRAP" == 1 ]]; then
  say "bootstrap images $TAG"
  if [[ "$DRY_RUN" == 1 ]]; then
    echo "+ docker login $REGISTRY; docker build/push $ORCHESTRATOR:$TAG and $SCORER:$TAG"
  else
    aws ecr get-login-password | docker login --username AWS --password-stdin "$REGISTRY"
    # No attestations: Lambda rejects the image index they wrap the image in.
    docker build --provenance=false --sbom=false -f "$REPO_ROOT/orchestrator/Dockerfile" -t "$REGISTRY/$ORCHESTRATOR:$TAG" "$REPO_ROOT"
    docker build --provenance=false --sbom=false -f "$REPO_ROOT/backend/inference/Dockerfile.lambda" -t "$REGISTRY/$SCORER:$TAG" "$REPO_ROOT/backend"
    docker push "$REGISTRY/$ORCHESTRATOR:$TAG"
    docker push "$REGISTRY/$SCORER:$TAG"
  fi
fi

# Configuration that is not secret. Secrets are SSM parameter NAMES here; the
# functions read the values with their own roles.
ORCHESTRATOR_ENV="Variables={INGEST_TOKEN_PARAMETER=$PARAM_INGEST_TOKEN,OTEL_ENDPOINT_PARAMETER=$PARAM_OTEL_ENDPOINT,OTEL_HEADERS_PARAMETER=$PARAM_OTEL_AUTH}"
SCORER_ENV="Variables={OTEL_ENABLED=true,OTEL_ENDPOINT_PARAMETER=$PARAM_OTEL_ENDPOINT,OTEL_HEADERS_PARAMETER=$PARAM_OTEL_AUTH,OTEL_SERVICE_NAME=$SCORER,DEPLOYMENT_ENVIRONMENT=production}"

ensure_function() {
  local name=$1 role=$2 memory=$3 timeout=$4 env=$5
  say "function $name"
  if [[ "$DRY_RUN" == 0 ]]; then
    aws logs create-log-group --log-group-name "/aws/lambda/$name" 2>/dev/null || true
  fi
  run aws logs put-retention-policy --log-group-name "/aws/lambda/$name" --retention-in-days 14
  if exists aws lambda get-function --function-name "$name"; then
    run aws lambda update-function-configuration --function-name "$name" \
      --role "arn:aws:iam::${ACCOUNT_ID}:role/$role" --memory-size "$memory" --timeout "$timeout" \
      --environment "$env" >/dev/null
    run aws lambda wait function-updated-v2 --function-name "$name"
  else
    run aws lambda create-function --function-name "$name" --package-type Image \
      --code "ImageUri=$REGISTRY/$name:$TAG" --role "arn:aws:iam::${ACCOUNT_ID}:role/$role" \
      --memory-size "$memory" --timeout "$timeout" --architectures x86_64 \
      --environment "$env" >/dev/null
    # A new function is Pending until its image is optimised; anything
    # configured before it is Active fails with ResourceConflictException.
    run aws lambda wait function-active-v2 --function-name "$name"
  fi
}

ensure_function "$ORCHESTRATOR" "$ORCHESTRATOR_ROLE" "$ORCHESTRATOR_MEMORY_MB" "$ORCHESTRATOR_TIMEOUT_S" "$ORCHESTRATOR_ENV"
# One at a time where the account allows it. A new account's concurrency quota
# is 10, all of which must stay unreserved, and AWS then refuses any
# reservation. That is acceptable: parallel invocations run in separate
# sandboxes with their own /tmp, so two workflows overlapping only costs GB-s.
if ! run aws lambda put-function-concurrency --function-name "$ORCHESTRATOR" \
     --reserved-concurrent-executions 1 >/dev/null; then
  # AWS has printed its reason above (expected: the account's unreserved
  # minimum). Anything else is worth reading before carrying on.
  echo "   reserved concurrency not set; runs may overlap in separate sandboxes" >&2
fi

# EventBridge Scheduler invokes asynchronously, so Lambda's OWN retry policy
# applies on top of the schedule's (default: 2 retries, events kept 6 h). A
# failed re-score would run three times and a failed ingest would re-run the
# whole workflow with fresh timestamps, i.e. new readings. No retries; an
# event older than 15 min is dropped rather than run late.
run aws lambda put-function-event-invoke-config --function-name "$ORCHESTRATOR" \
  --maximum-retry-attempts 0 --maximum-event-age-in-seconds 900 >/dev/null

ensure_function "$SCORER" "$SCORER_ROLE" "$SCORER_MEMORY_MB" "$SCORER_TIMEOUT_S" "$SCORER_ENV"
