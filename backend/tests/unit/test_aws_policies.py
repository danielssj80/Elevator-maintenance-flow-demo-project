"""The IAM documents under deploy/aws/policies/, asserted for least privilege.

These are the permissions the provisioning scripts attach. A wildcard here is
not a style issue: the instance role is reachable from a public web host, and
the deploy role from every merge to main.
"""

import json
import pathlib

import pytest

POLICIES = pathlib.Path(__file__).resolve().parents[3] / "deploy" / "aws" / "policies"
GUARDED_SERVICES = ("lambda:", "ssm:", "ecr:", "bedrock:", "logs:", "kms:", "iam:")
# The one action AWS offers no resource-level permission for.
RESOURCELESS_ACTIONS = {"ecr:GetAuthorizationToken"}

PERMISSION_POLICIES = sorted(
    p for p in POLICIES.glob("*.json") if not p.name.endswith("-trust.json") and p.name != "ecr-lifecycle.json"
)


def _statements(path: pathlib.Path) -> list[dict]:
    statements = json.loads(path.read_text())["Statement"]
    return statements if isinstance(statements, list) else [statements]


def _as_list(value) -> list:
    return value if isinstance(value, list) else [value]


def test_the_policy_set_is_the_expected_one():
    assert {p.name for p in PERMISSION_POLICIES} == {
        "deploy-lambda-images.json",
        "host-read-secrets.json",
        "instance-invoke-scorer.json",
        "orchestrator-function.json",
        "scheduler-invoke.json",
        "scorer-function.json",
    }


@pytest.mark.parametrize("path", PERMISSION_POLICIES, ids=lambda p: p.name)
def test_no_guarded_action_has_a_wildcard_resource(path):
    for statement in _statements(path):
        assert statement["Effect"] == "Allow"
        actions = _as_list(statement["Action"])
        resources = _as_list(statement["Resource"])
        for action in actions:
            assert "*" not in action, f"{path.name}: wildcard action {action}"
        if set(actions) <= RESOURCELESS_ACTIONS:
            continue
        for resource in resources:
            # Any `*`, not just a bare one: `parameter/elevator/orchestrator/*`
            # would quietly cover the ingest token. The one allowed form is a
            # named log group's streams, `...:log-group:<name>:*`.
            log_streams = ":log-group:" in resource and resource.endswith(":*") and resource.count("*") == 1
            assert "*" not in resource or log_streams, f"{path.name}: {resource}"
        assert any(a.startswith(GUARDED_SERVICES) for a in actions)


def test_the_instance_may_invoke_only_the_scorer():
    [statement] = _statements(POLICIES / "instance-invoke-scorer.json")

    assert _as_list(statement["Action"]) == ["lambda:InvokeFunction"]
    assert _as_list(statement["Resource"]) == [
        "arn:aws:lambda:${AWS_REGION}:${ACCOUNT_ID}:function:elevator-scorer"
    ]


def test_the_scorer_cannot_read_the_ingest_token():
    for statement in _statements(POLICIES / "scorer-function.json"):
        for resource in _as_list(statement["Resource"]):
            assert "ingest-token" not in resource


def test_the_scheduler_may_invoke_only_the_orchestrator():
    [statement] = _statements(POLICIES / "scheduler-invoke.json")

    assert _as_list(statement["Resource"]) == [
        "arn:aws:lambda:${AWS_REGION}:${ACCOUNT_ID}:function:elevator-orchestrator"
    ]


def test_the_deploy_role_touches_only_the_two_functions_and_repositories():
    resources = {
        r
        for s in _statements(POLICIES / "deploy-lambda-images.json")
        for r in _as_list(s["Resource"])
        if r != "*"
    }
    assert resources == {
        "arn:aws:ecr:${AWS_REGION}:${ACCOUNT_ID}:repository/elevator-orchestrator",
        "arn:aws:ecr:${AWS_REGION}:${ACCOUNT_ID}:repository/elevator-scorer",
        "arn:aws:lambda:${AWS_REGION}:${ACCOUNT_ID}:function:elevator-orchestrator",
        "arn:aws:lambda:${AWS_REGION}:${ACCOUNT_ID}:function:elevator-scorer",
    }


def test_the_scheduler_trust_is_pinned_to_this_account():
    [statement] = _statements(POLICIES / "scheduler-trust.json")

    assert statement["Condition"]["StringEquals"]["aws:SourceAccount"] == "${ACCOUNT_ID}"


P = "arn:aws:ssm:${AWS_REGION}:${ACCOUNT_ID}:parameter/elevator/"
LOGS = "arn:aws:logs:${AWS_REGION}:${ACCOUNT_ID}:log-group:/aws/lambda/"


def _resources(name: str) -> set[str]:
    return {r for s in _statements(POLICIES / name) for r in _as_list(s["Resource"])}


def test_each_function_reads_exactly_its_parameters_and_writes_its_own_logs():
    """Pinned sets, so any added resource — wildcard or not — is a test change
    someone has to make on purpose."""
    otel = {P + "otel/grafana-otlp-endpoint", P + "otel/grafana-otlp-auth"}

    assert _resources("orchestrator-function.json") == otel | {
        P + "orchestrator/ingest-token",
        LOGS + "elevator-orchestrator:*",
    }
    assert _resources("scorer-function.json") == otel | {LOGS + "elevator-scorer:*"}
    assert _resources("host-read-secrets.json") == otel | {P + "orchestrator/ingest-token"}
