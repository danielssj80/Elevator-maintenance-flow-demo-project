"""The guards in infra/terraform/, read as configuration.

`terraform validate` proves the configuration is well-formed; it says nothing
about what it would do to the account. These tests hold the properties that
matter and that a reasonable-looking edit could quietly undo: no secret in the
state, CI owning the function image, pre-existing resources only referenced,
and the cutover switch and retry settings actually wired.

Text-level on purpose: no HCL parser is a backend dependency, and every
assertion targets a short, distinctive line.
"""

import pathlib
import re

INFRA = pathlib.Path(__file__).resolve().parents[3] / "infra" / "terraform"
POLICIES = INFRA.parents[1] / "deploy" / "aws" / "policies"


def _tf() -> str:
    files = sorted(INFRA.glob("*.tf"))
    assert files, "infra/terraform has no .tf files"
    return "\n".join(f.read_text() for f in files)


def _block(text: str, header: str) -> str:
    """The body of the first block whose header line matches `header`."""
    match = re.search(header + r"\s*\{", text)
    assert match, f"no block matching {header!r}"
    depth, i = 1, match.end()
    while depth:
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        i += 1
    return text[match.end() : i - 1]


def test_no_ssm_parameter_passes_through_terraform():
    """The provider refreshes a SecureString's decrypted value into the state,
    `ignore_changes` notwithstanding. deploy/aws/30-ssm.sh owns the parameters."""
    assert not re.search(r'(resource|data)\s+"aws_ssm_parameter', _tf())


def test_no_secret_looking_literal_is_committed():
    text = _tf()
    for pattern in (r"\b(AKIA|ASIA)[0-9A-Z]{16}\b", r"Authorization=Basic", r"\bglc_", r"local-dev-ingest-token"):
        assert not re.search(pattern, text), pattern


def test_ci_owns_the_function_image():
    text = _tf()
    for name in ("orchestrator", "scorer"):
        body = _block(text, rf'resource\s+"aws_lambda_function"\s+"{name}"')
        lifecycle = _block(body, r"lifecycle")
        assert re.search(r"ignore_changes\s*=\s*\[[^\]]*\bimage_uri\b", lifecycle), name


def test_pre_existing_resources_are_referenced_never_managed():
    text = _tf()
    assert re.search(r'data\s+"aws_iam_role"\s+"instance"', text)
    assert re.search(r'data\s+"aws_iam_role"\s+"deploy"', text)
    assert re.search(r'data\s+"aws_iam_policy"\s+"bedrock"', text)
    for name in ("elevator-ssm-role", "github-actions-deploy", "ElevatorBedrockInvokeNova"):
        # Their names appear only as variable defaults, never in a resource.
        for resource in re.finditer(r'resource\s+"[^"]+"\s+"[^"]+"\s*\{', text):
            body = _block(text[resource.start():], re.escape(resource.group(0)[:-1].rstrip()))
            assert f'"{name}"' not in body, f"{name} inside {resource.group(0)}"
    assert not re.search(r'resource\s+"aws_(instance|iam_openid_connect_provider|route53_record)"', text)


def test_the_cutover_switch_drives_schedules_and_silence_alarms():
    text = _tf()
    schedule = _block(text, r'resource\s+"aws_scheduler_schedule"\s+"this"')
    assert re.search(r'state\s*=\s*var\.schedules_enabled\s*\?\s*"ENABLED"\s*:\s*"DISABLED"', schedule)
    silence = _block(text, r'resource\s+"aws_cloudwatch_metric_alarm"\s+"silence"')
    assert re.search(r"actions_enabled\s*=\s*var\.schedules_enabled\b", silence)
    assert re.search(r'treat_missing_data\s*=\s*"breaching"', silence)
    default = _block(text, r'variable\s+"schedules_enabled"')
    assert re.search(r"default\s*=\s*false", default), "schedules must start disabled"


def test_no_retries_at_either_layer():
    text = _tf()
    invoke = _block(text, r'resource\s+"aws_lambda_function_event_invoke_config"\s+"orchestrator"')
    assert re.search(r"maximum_retry_attempts\s*=\s*0\b", invoke)
    schedule = _block(text, r'resource\s+"aws_scheduler_schedule"\s+"this"')
    assert re.search(r"retry_policy\s*\{\s*maximum_retry_attempts\s*=\s*0\s*\}", schedule)


def test_every_policy_document_is_the_tested_one():
    """IAM documents come from deploy/aws/policies/ (asserted by
    test_aws_policies.py), not from inline JSON that no test reads."""
    text = _tf()
    for path in POLICIES.glob("*.json"):
        assert path.name in text, f"{path.name} is not used by Terraform"
    for body in re.findall(r'resource\s+"aws_iam_(?:policy|role)"[^{]*\{(.*?)\n\}', text, re.S):
        assert "jsonencode" not in body, "inline IAM document"


def test_state_is_encrypted_and_locked():
    backend = _block(_tf(), r'backend\s+"s3"')
    assert re.search(r"encrypt\s*=\s*true", backend)
    assert re.search(r"use_lockfile\s*=\s*true", backend)
    assert re.search(r'bucket\s*=\s*"elevator-tfstate-150911080650"', backend)


def test_only_the_intended_account_can_be_touched():
    provider = _block(_tf(), r'provider\s+"aws"')
    assert re.search(r"allowed_account_ids\s*=\s*\[var\.account_id\]", provider)
