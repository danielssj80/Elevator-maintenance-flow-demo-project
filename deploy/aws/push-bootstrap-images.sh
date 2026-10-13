#!/usr/bin/env bash
# Build both Lambda images and push them to ECR, tagged with the current
# commit. Needed exactly once, between creating the repositories and creating
# the functions (a function can only be created from an image already in ECR):
#
#   terraform -chdir=infra/terraform apply -target=aws_ecr_repository.this
#   deploy/aws/push-bootstrap-images.sh
#   terraform -chdir=infra/terraform apply -var image_tag=$(git rev-parse HEAD)
#
# After that, .github/workflows/lambda-images.yml publishes on every merge.
# Usage: deploy/aws/push-bootstrap-images.sh [--dry-run]
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh" "$@"

REPO_ROOT="$(cd "$HERE/../.." && pwd)"
TAG="$(git -C "$REPO_ROOT" rev-parse HEAD)"
if [[ -n "$(git -C "$REPO_ROOT" status --porcelain -- orchestrator backend n8n)" ]]; then
  echo "uncommitted changes under orchestrator/, backend/ or n8n/: the image would not match $TAG" >&2
  exit 1
fi

say "bootstrap images $TAG"
if [[ "$DRY_RUN" == 1 ]]; then
  echo "+ docker login $REGISTRY; docker build/push $ORCHESTRATOR:$TAG and $SCORER:$TAG" >&2
  exit 0
fi

# No attestations: Lambda rejects the image index they wrap the image in.
docker build --provenance=false --sbom=false -f "$REPO_ROOT/orchestrator/Dockerfile" \
  -t "$REGISTRY/$ORCHESTRATOR:$TAG" "$REPO_ROOT"
docker build --provenance=false --sbom=false -f "$REPO_ROOT/backend/inference/Dockerfile.lambda" \
  -t "$REGISTRY/$SCORER:$TAG" "$REPO_ROOT/backend"

# Log in and push with a throwaway Docker config that has no credential
# helper: the Windows credential store behind Docker Desktop rejects the long
# ECR token ("error storing credentials"), and the token should not outlive
# this script anyway.
PUSH_CONFIG=$(mktemp -d)
trap 'rm -rf "$PUSH_CONFIG"' EXIT
echo '{}' >"$PUSH_CONFIG/config.json"
aws ecr get-login-password | DOCKER_CONFIG="$PUSH_CONFIG" docker login --username AWS --password-stdin "$REGISTRY"
DOCKER_CONFIG="$PUSH_CONFIG" docker push "$REGISTRY/$ORCHESTRATOR:$TAG"
DOCKER_CONFIG="$PUSH_CONFIG" docker push "$REGISTRY/$SCORER:$TAG"
echo "pushed; next: terraform -chdir=infra/terraform apply -var image_tag=$TAG"
