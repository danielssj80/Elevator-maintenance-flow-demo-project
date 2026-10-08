"""Invariants of the committed n8n workflow definitions.

One JSON serves two places: the local stack, where the Schedule Trigger fires,
and the production Lambda, where EventBridge calls the Webhook Trigger and the
image build disables every Schedule (see orchestrator/). These tests hold the
repository side of that bargain; the image side is checked in
`test_orchestrator_image.py`.
"""

import json
import pathlib

import pytest

WORKFLOWS_DIR = pathlib.Path(__file__).parents[3] / "n8n" / "workflows"
SLUGS = ["telemetry-ingest", "daily-inference-and-digest"]

SCHEDULE = "n8n-nodes-base.scheduleTrigger"
WEBHOOK = "n8n-nodes-base.webhook"
HTTP = "n8n-nodes-base.httpRequest"

EXECUTION_ID_EXPRESSION = (
    "={{ $('Webhook').isExecuted ? $('Webhook').first().json.body.invocationId "
    ": $execution.id }}"
)


def _load(slug: str) -> dict:
    return json.loads((WORKFLOWS_DIR / f"{slug}.json").read_text())


def _nodes_of(workflow: dict, node_type: str) -> list[dict]:
    return [n for n in workflow["nodes"] if n["type"] == node_type]


def _targets(workflow: dict, node_name: str) -> list[str]:
    outputs = workflow["connections"].get(node_name, {}).get("main", [])
    return [link["node"] for branch in outputs for link in branch]


@pytest.fixture(params=SLUGS)
def workflow(request) -> dict:
    return _load(request.param) | {"_slug": request.param}


def test_each_workflow_has_exactly_one_webhook_named_by_its_slug(workflow):
    webhooks = _nodes_of(workflow, WEBHOOK)

    assert len(webhooks) == 1, f"{workflow['_slug']}: {len(webhooks)} webhooks"
    [webhook] = webhooks
    assert webhook["name"] == "Webhook", "the execution-id expression refers to it by name"
    assert webhook["parameters"]["httpMethod"] == "POST"
    assert webhook["parameters"]["path"] == workflow["_slug"]
    # The handler logs what the webhook returns; for the daily run that is the
    # digest, and there is no execution history to read it from afterwards.
    assert webhook["parameters"]["responseMode"] == "lastNode"
    assert not webhook.get("disabled", False)


def test_the_webhook_starts_the_same_path_as_the_schedule(workflow):
    [schedule] = _nodes_of(workflow, SCHEDULE)
    [webhook] = _nodes_of(workflow, WEBHOOK)

    assert _targets(workflow, webhook["name"]) == _targets(workflow, schedule["name"])
    assert _targets(workflow, webhook["name"]), "the webhook is wired to nothing"


def test_the_schedule_stays_enabled_for_the_local_stack(workflow):
    """Only the Lambda image disables it. Disabled here, local schedules stop."""
    [schedule] = _nodes_of(workflow, SCHEDULE)

    assert not schedule.get("disabled", False)


def test_http_nodes_use_the_local_address_and_never_read_the_environment(workflow):
    """The repository holds the local compose address; the Lambda image build
    rewrites it to the production origin (orchestrator/seed/prepare-workflows.mjs).

    Nothing reads `$env`: allowing it would let any expression or Code node read
    the ingest token, the OTLP auth header and the AWS credentials, all of which
    are in n8n's environment in the Lambda.
    """
    for node in _nodes_of(workflow, HTTP):
        url = node["parameters"]["url"]
        assert url.startswith("http://backend:8000/api/"), f"{workflow['_slug']} / {node['name']}: {url}"
    assert "$env" not in json.dumps(workflow), workflow["_slug"]


def test_every_http_node_sends_the_execution_identity(workflow):
    """Production's n8n numbers every execution 1 (fresh database per
    invocation); the Lambda request id is what leads to the invocation's log."""
    for node in _nodes_of(workflow, HTTP):
        params = node["parameters"]
        assert params.get("sendHeaders") is True, node["name"]
        headers = {h["name"]: h["value"] for h in params["headerParameters"]["parameters"]}
        assert headers.get("X-N8N-Execution-Id") == EXECUTION_ID_EXPRESSION, node["name"]
        assert headers.get("X-N8N-Workflow-Id") == "={{ $workflow.id }}", node["name"]


def test_no_header_value_is_a_literal_secret(workflow):
    """The token travels as a credential, never as a header typed into a node."""
    for node in _nodes_of(workflow, HTTP):
        headers = node["parameters"].get("headerParameters", {}).get("parameters", [])
        for header in headers:
            assert header["name"].lower() != "x-ingest-token", node["name"]
            assert header["value"].startswith("={{"), (node["name"], header["name"])


def test_definitions_carry_no_credentials_or_instance_internals(workflow):
    for node in workflow["nodes"]:
        assert "credentials" not in node, node["name"]
    assert "instanceId" not in workflow.get("meta", {})
    assert "versionId" not in workflow
