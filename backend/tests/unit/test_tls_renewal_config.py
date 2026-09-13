"""The guards for a renewal that failed silently for ninety-three days.

On 2026-09-13 the wildcard certificate for `*.dsaavedra.dev` expired and took
both sites down. It had never renewed: the crontab line began with a bare
`certbot`, and `cronie` runs jobs with `PATH=/usr/bin:/bin` while the
pip-installed binary lives in `/usr/local/bin`. The specification's S7 was marked
verified on the strength of a `certbot renew --dry-run` typed into an interactive
shell — which inherits the operator's `PATH` and, by certbot's own default, runs
no deploy hook. It tested neither clause of the requirement.

So these tests read the files that configure the host, and five of them *run* the
installer against a throwaway prefix with stubbed `systemctl` and `crontab`. They
are the tests that would have been red on 12 June.

See `openspec/changes/harden-tls-renewal/reports/2026-09-13-incident-tls-expiry.md`.
"""

import configparser
import os
import pathlib
import re
import subprocess

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
TLS_DIR = REPO_ROOT / "deploy" / "tls"
SERVICE = TLS_DIR / "certbot-renew.service"
TIMER = TLS_DIR / "certbot-renew.timer"
HOOK = TLS_DIR / "reload-nginx-deploy-hook.sh"
INSTALLER = TLS_DIR / "install-renewal.sh"
EXPIRY_SCRIPT = REPO_ROOT / "scripts" / "check-tls-expiry.sh"
DEPLOY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy.yml"
EXPIRY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tls-expiry-check.yml"

PRODUCTION_HOSTS = ("elevator.dsaavedra.dev", "dsaavedra.dev")


def _unit_section(path: pathlib.Path, section: str) -> dict[str, str]:
    """One section of a systemd unit, with its keys' case preserved.

    systemd permits a key to repeat (`ExecStart=` twice, for instance), which
    `configparser` rejects unless `strict=False`; the last wins here, and the one
    test that cares about repetition reads the raw text instead.
    """
    assert path.exists(), f"{path} is missing"
    parser = configparser.ConfigParser(strict=False, allow_no_value=True, interpolation=None)
    parser.optionxform = str  # systemd keys are case-sensitive
    parser.read_string(path.read_text())
    assert parser.has_section(section), f"{path.name} has no [{section}] section"
    return dict(parser[section])


def _workflow(path: pathlib.Path) -> dict:
    assert path.exists(), f"{path} is missing"
    return yaml.safe_load(path.read_text())


def _triggers(workflow: dict) -> dict:
    """A workflow's `on:` block.

    YAML 1.1 reads a bare `on` as the boolean `True`, which is why this is not
    simply `workflow["on"]`.
    """
    return workflow.get("on", workflow.get(True, {})) or {}


# --------------------------------------------------------------------------- #
# The unit files
# --------------------------------------------------------------------------- #


def test_renewal_unit_invokes_certbot_by_absolute_path():
    """The bug itself.

    `ExecStart=certbot renew` is what the crontab line was, in effect, and it
    resolved to nothing under the scheduler's PATH for ninety-three days. systemd
    refuses a relative ExecStart outright, which is the substantive reason for
    preferring a unit over a crontab line — but only if the path we ship is in
    fact absolute, so assert it here rather than trusting systemd to reject a
    file nobody would notice being rejected.
    """
    exec_start = _unit_section(SERVICE, "Service")["ExecStart"]
    binary, *arguments = exec_start.split()

    assert binary.startswith("/"), (
        f"ExecStart must name certbot by absolute path, got {binary!r}. A bare "
        "binary name is the defect that expired the certificate on 2026-09-10"
    )
    assert binary.endswith("certbot"), f"ExecStart should run certbot, got {binary!r}"
    assert "renew" in arguments, f"ExecStart should renew, got {exec_start!r}"


def test_timer_checks_twice_a_day_and_catches_up_after_downtime():
    """Let's Encrypt asks every client for twice daily; `Persistent` covers reboots.

    One attempt a day gives thirty chances inside the renewal window and no
    second chance on the day something is briefly wrong. `Persistent=true` runs a
    trigger missed while the instance was powered off, which a crontab line
    cannot do at all.
    """
    calendars = [
        line.split("=", 1)[1].strip()
        for line in TIMER.read_text().splitlines()
        if line.strip().startswith("OnCalendar=")
    ]
    assert calendars, f"{TIMER.name} must set OnCalendar"

    # "*-*-* 03,15:00:00" is two runs; two separate OnCalendar lines are also two.
    runs_per_day = sum(len(spec.split()[-1].split(":")[0].split(",")) for spec in calendars)
    assert runs_per_day >= 2, (
        f"the timer must attempt renewal at least twice a day, got {runs_per_day} "
        f"from {calendars!r}"
    )

    timer = _unit_section(TIMER, "Timer")
    assert timer.get("Persistent", "").lower() in ("true", "yes", "on", "1"), (
        "Persistent=true is what runs a trigger missed while the instance was off"
    )
    assert "WantedBy" in _unit_section(TIMER, "Install"), (
        "without [Install] WantedBy=, `systemctl enable` has nothing to link"
    )


def test_deploy_hook_reloads_nginx_without_requiring_a_tty():
    """The second defect in the same crontab line.

    `docker compose exec` allocates a TTY by default and fails when stdin is not
    one. Under a timer there is no more TTY than under cron, so a renewal would
    land on disk while nginx went on serving the expired certificate it holds in
    memory. The live crontab had acquired `-T`; no file in this repository showed
    it, which is the drift this change exists to end.
    """
    assert HOOK.exists(), f"{HOOK} is missing"
    hook = HOOK.read_text()

    assert re.search(r"\bexec\s+-T\b", hook), (
        "the reload must pass `exec -T`: there is no TTY in a systemd timer"
    )
    assert "nginx -s reload" in hook, "the hook must reload nginx"
    assert "cd /opt/elevator" in hook and "-f docker-compose.prod.yml" in hook, (
        "invoke Compose exactly as deploy.yml does, so both derive the same "
        "project name and `exec` cannot fail to find the container"
    )


# --------------------------------------------------------------------------- #
# The installer, executed
# --------------------------------------------------------------------------- #


def _run_installer(
    tmp_path: pathlib.Path,
    *,
    certbot_present: bool = True,
    crontab_content: str | None = None,
) -> tuple[subprocess.CompletedProcess, pathlib.Path, str, pathlib.Path]:
    """Run the real installer against a throwaway filesystem.


    `PREFIX` relocates every destination and the binary check; `SYSTEMCTL` and
    `CRONTAB` are stubs that record how they were called. Nothing here touches
    the developer's machine, and the script under test is the one the deploy runs
    — not a copy of its logic.
    """
    assert INSTALLER.exists(), f"{INSTALLER} is missing"
    prefix = tmp_path / "rootfs"
    (prefix / "usr/local/bin").mkdir(parents=True)
    (prefix / "root").mkdir(parents=True)
    if certbot_present:
        certbot = prefix / "usr/local/bin/certbot"
        certbot.write_text("#!/bin/sh\nexit 0\n")
        certbot.chmod(0o755)

    calls = tmp_path / "calls.log"
    stub_dir = tmp_path / "stubs"
    stub_dir.mkdir()

    systemctl = stub_dir / "systemctl"
    systemctl.write_text(f'#!/bin/sh\necho "systemctl $*" >> "{calls}"\nexit 0\n')
    systemctl.chmod(0o755)

    crontab_file = tmp_path / "crontab.txt"
    if crontab_content is not None:
        crontab_file.write_text(crontab_content)
    crontab = stub_dir / "crontab"
    crontab.write_text(
        "#!/bin/sh\n"
        f'echo "crontab $*" >> "{calls}"\n'
        "case \"$1\" in\n"
        f'  -l) if [ -f "{crontab_file}" ]; then cat "{crontab_file}"; else\n'
        '        echo "no crontab for root" >&2; exit 1; fi ;;\n'
        f'  -) cat > "{crontab_file}" ;;\n'
        "esac\n"
        "exit 0\n"
    )
    crontab.chmod(0o755)

    result = subprocess.run(
        ["sh", str(INSTALLER)],
        capture_output=True,
        text=True,
        timeout=60,
        env={
            **os.environ,
            "PREFIX": str(prefix),
            "SYSTEMCTL": str(systemctl),
            "CRONTAB": str(crontab),
        },
    )
    return result, prefix, calls.read_text() if calls.exists() else "", crontab_file


def test_installer_installs_the_units_and_enables_the_timer(tmp_path):
    result, prefix, calls, _ = _run_installer(tmp_path)

    assert result.returncode == 0, result.stderr
    service = prefix / "etc/systemd/system/certbot-renew.service"
    timer = prefix / "etc/systemd/system/certbot-renew.timer"
    hook = prefix / "etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh"

    assert service.read_text() == SERVICE.read_text()
    assert timer.read_text() == TIMER.read_text()
    assert hook.read_text() == HOOK.read_text(), (
        "the hook must be installed where certbot runs it after any successful "
        "renewal, whoever invoked certbot"
    )
    assert os.access(hook, os.X_OK), "certbot only runs hooks that are executable"

    assert "daemon-reload" in calls
    assert re.search(r"enable .*--now.* certbot-renew\.timer|enable --now certbot-renew\.timer", calls), (
        f"the timer must be enabled and started, calls were:\n{calls}"
    )


def test_installer_fails_when_the_binary_the_unit_names_is_missing(tmp_path):
    """The check whose absence cost ninety-three days.

    A renewal unit pointing at a binary that is not there is exactly the
    configuration that was live, and it produced no error anywhere. Here it
    fails, before anything is enabled, and the deploy run goes red.
    """
    result, _, calls, _ = _run_installer(tmp_path, certbot_present=False)

    assert result.returncode != 0, "a missing certbot binary must fail the install"
    assert "certbot" in (result.stderr + result.stdout)
    assert "enable" not in calls, (
        "check the binary before enabling the timer, so a broken install is never "
        "left looking active"
    )


def test_installer_removes_the_legacy_crontab_renewer_and_keeps_a_backup(tmp_path):
    """Two renewers are worse than one: nobody can tell which is live."""
    legacy = (
        "0 3 * * * certbot renew --quiet && docker compose "
        "-f /opt/elevator/docker-compose.prod.yml exec -T nginx nginx -s reload\n"
        "@daily /usr/local/bin/unrelated-job\n"
    )
    result, prefix, _, crontab_file = _run_installer(tmp_path, crontab_content=legacy)

    assert result.returncode == 0, result.stderr
    remaining = crontab_file.read_text()
    assert "certbot renew" not in remaining, "the legacy renewer must be removed"
    assert "unrelated-job" in remaining, "unrelated crontab entries must survive"

    backups = list((prefix / "root").glob("crontab.bak.*"))
    assert backups, "back the crontab up before rewriting it"
    assert "certbot renew" in backups[0].read_text()


def test_installer_succeeds_on_a_host_with_no_crontab(tmp_path):
    """`crontab -l` exits 1 when there is no crontab; that is not an error here."""
    result, _, _, _ = _run_installer(tmp_path, crontab_content=None)

    assert result.returncode == 0, result.stderr


def test_installer_running_twice_changes_nothing(tmp_path):
    """It runs on every deploy, so a second run must be a no-op, not a surprise."""
    first, prefix, _, _ = _run_installer(tmp_path, crontab_content="@daily /bin/true\n")
    assert first.returncode == 0, first.stderr
    installed = (prefix / "etc/systemd/system/certbot-renew.timer").read_text()

    second_tmp = tmp_path / "again"
    second_tmp.mkdir()
    second, second_prefix, calls, _ = _run_installer(second_tmp, crontab_content="@daily /bin/true\n")

    assert second.returncode == 0, second.stderr
    assert (second_prefix / "etc/systemd/system/certbot-renew.timer").read_text() == installed
    assert "daemon-reload" in calls


# --------------------------------------------------------------------------- #
# Detection off the host
# --------------------------------------------------------------------------- #


def test_expiry_threshold_sits_inside_the_renewal_window():
    """21 days: renewal starts at 30, so an alert means broken, not merely due.

    A threshold at or above 30 days fires while renewal is still expected to
    happen, which teaches its reader to ignore it; a threshold at 3 days is an
    outage notification. This reads the script's default textually — the live
    behaviour is proven in step 10 against production.
    """
    assert EXPIRY_SCRIPT.exists(), f"{EXPIRY_SCRIPT} is missing"
    match = re.search(r"(?i)min_days.*?:-\s*(\d+)", EXPIRY_SCRIPT.read_text())
    assert match, "the script must define a default day threshold"

    default_days = int(match.group(1))
    assert 14 <= default_days <= 29, (
        f"the default threshold is {default_days} days; it must leave slack after "
        "renewal's 30-day window opens and before expiry"
    )


def test_expiry_check_validates_the_chain_without_trust_overrides():
    """An expired certificate is only one of the ways TLS breaks."""
    script = EXPIRY_SCRIPT.read_text()

    assert "curl" in script, "the check must make a verifying request, not only read dates"
    assert not re.search(r"(?<!\w)-k(?!\w)|--insecure", script), (
        "the check must not disable verification; that is what hid the outage "
        "from every other health check in the system"
    )


def test_expiry_check_fails_when_no_certificate_can_be_read():
    """It must never pass for want of an expiry date to compare.

    `.invalid` cannot resolve, by RFC 2606, so this needs no network.
    """
    assert EXPIRY_SCRIPT.exists(), f"{EXPIRY_SCRIPT} is missing"
    result = subprocess.run(
        ["sh", str(EXPIRY_SCRIPT), "no-such-host.invalid"],
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode != 0, (
        "an unreachable host must fail the check, not pass it silently:\n"
        f"{result.stdout}{result.stderr}"
    )


def test_expiry_workflow_is_scheduled_and_can_be_run_on_demand():
    """GitHub disables scheduled workflows after 60 days of repository inactivity.

    `workflow_dispatch` is the manual path when that happens, and deploy.yml
    running the same script is the other mitigation. See design.md §4 — this is
    stated as a limitation, not solved.
    """
    triggers = _triggers(_workflow(EXPIRY_WORKFLOW))

    assert triggers.get("schedule"), "the expiry check must run on a schedule"
    assert "workflow_dispatch" in triggers, "it must also be runnable on demand"

    text = EXPIRY_WORKFLOW.read_text()
    for host in PRODUCTION_HOSTS:
        assert host in text, f"{host} is served by the same certificate and must be checked"


def test_deploy_workflow_installs_the_renewal_after_the_smoke_check():
    """Renewal configuration must not be able to block an application deploy.

    It must still turn the run red: a warning that fails nothing is how thirty
    consecutive renewal failures went unnoticed.
    """
    steps = _workflow(DEPLOY_WORKFLOW)["jobs"]["deploy"]["steps"]
    names = [str(step.get("name", "")) for step in steps]
    bodies = [str(step.get("run", "")) + str(step.get("with", "")) for step in steps]

    smoke = next((i for i, name in enumerate(names) if "smoke" in name.lower()), None)
    assert smoke is not None, "deploy.yml should still have a smoke check"

    install = next(
        (i for i, (name, body) in enumerate(zip(names, bodies)) if "install-renewal.sh" in body),
        None,
    )
    assert install is not None, "deploy.yml must run deploy/tls/install-renewal.sh"
    assert install > smoke, (
        "install the renewal configuration after the smoke check, so a failure "
        "there cannot prevent or revert an application deploy"
    )

    assert any("check-tls-expiry.sh" in body for body in bodies), (
        "the deploy should also report certificate health"
    )
