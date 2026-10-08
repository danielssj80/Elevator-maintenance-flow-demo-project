"""The CI workflow that publishes the two Lambda images, read as configuration.

It holds AWS write access (ECR push, Lambda code updates) on every merge, so
its trigger, its identity and its blast radius are asserted rather than
trusted. And it must stay a workflow of its own: `deploy.yml` runs when
`build-images.yml` succeeds, so a Lambda job inside that workflow would let an
unprovisioned function block the application deploy.
"""

import pathlib
import re

import yaml

WORKFLOWS = pathlib.Path(__file__).resolve().parents[3] / ".github" / "workflows"
LAMBDA_IMAGES = WORKFLOWS / "lambda-images.yml"
FUNCTIONS = ("elevator-orchestrator", "elevator-scorer")


def _load(path: pathlib.Path) -> dict:
    assert path.exists(), f"{path.name} is missing"
    return yaml.safe_load(path.read_text())


def _triggers(workflow: dict) -> dict:
    # PyYAML reads the bare key `on` as boolean True.
    return workflow.get("on", workflow.get(True))


def test_it_runs_only_on_pushes_to_main():
    triggers = _triggers(_load(LAMBDA_IMAGES))

    assert set(triggers) == {"push"}, triggers
    assert triggers["push"]["branches"] == ["main"]


def test_it_assumes_the_deploy_role_through_oidc_and_holds_no_aws_secret():
    workflow = _load(LAMBDA_IMAGES)
    text = LAMBDA_IMAGES.read_text()

    assert workflow["permissions"] == {"contents": "read", "id-token": "write"}
    assert "vars.AWS_DEPLOY_ROLE_ARN" in text
    assert not re.search(r"secrets\.AWS_|AWS_SECRET_ACCESS_KEY|AWS_ACCESS_KEY_ID", text)


def test_both_functions_are_updated_and_waited_for():
    text = LAMBDA_IMAGES.read_text()

    for function in FUNCTIONS:
        assert re.search(rf"update-function-code\s+--function-name\s+{function}\b", text), function
        assert re.search(rf"wait function-updated-v2\s+--function-name\s+{function}\b", text), function
    # Every image is pinned to the commit, never to a moving tag.
    assert ":latest" not in text
    assert text.count("${{ github.sha }}") >= 2


def test_pushes_are_serialised():
    workflow = _load(LAMBDA_IMAGES)

    assert workflow["concurrency"]["cancel-in-progress"] is False
    assert workflow["concurrency"]["group"] == "lambda-images"


def test_it_is_not_part_of_the_workflow_the_deploy_waits_for():
    build = (WORKFLOWS / "build-images.yml").read_text()
    deploy = _triggers(_load(WORKFLOWS / "deploy.yml"))

    for marker in ("update-function-code", "amazon-ecr-login", "id-token"):
        assert marker not in build, marker
    assert deploy["workflow_run"]["workflows"] == ["Build and push images"]


def test_every_lambda_image_build_disables_attestations():
    """Lambda takes a single image manifest. Docker 29 (containerd store) wraps
    even a plain `docker build` in an index carrying provenance and SBOM
    attestations, and Lambda rejects that at create or update time — after the
    push, so CI would be green up to the last step. Verified locally: without
    the flags the descriptor is `vnd.oci.image.index.v1+json`, with them a
    single `vnd.oci.image.manifest.v1+json`.
    """
    sources = [LAMBDA_IMAGES, WORKFLOWS.parents[1] / "deploy" / "aws" / "40-lambda.sh"]
    builds = [
        line.strip()
        for path in sources
        for line in path.read_text().splitlines()
        if "docker build" in line and not line.strip().startswith(("#", "echo"))
    ]

    assert len(builds) == 4, builds
    for line in builds:
        assert "--provenance=false" in line and "--sbom=false" in line, line
