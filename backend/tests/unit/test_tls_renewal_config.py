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
import socket
import subprocess
import time

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


def _code(path: pathlib.Path) -> str:
    """The file with its comment lines removed.

    A guard that can be satisfied by its own explanatory comment is not a guard.
    The first mutation run proved it: deleting `exec -T` from the hook's actual
    command left this file green, because the comment above that command explains
    why `exec -T` matters and the assertion found it there.
    """
    assert path.exists(), f"{path} is missing"
    return "\n".join(
        line for line in path.read_text().splitlines() if not line.lstrip().startswith("#")
    )


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
    hook = _code(HOOK)

    assert re.search(r"\bexec\s+-T\b", hook), (
        "the reload must pass `exec -T`: there is no TTY in a systemd timer"
    )
    assert "nginx -s reload" in hook, "the hook must reload nginx"
    assert "cd /opt/elevator" in hook and "-f docker-compose.prod.yml" in hook, (
        "invoke Compose exactly as deploy.yml does, so both derive the same "
        "project name and `exec` cannot fail to find the container"
    )
    assert "/opt/deploy.lock" in hook, (
        "take the same lock both deploy pipelines take around `docker compose up` "
        "on this shared nginx: a renewal landing mid-recreation loses its reload "
        "permanently, because certbot will not run the hook again"
    )


# --------------------------------------------------------------------------- #
# The installer, executed
# --------------------------------------------------------------------------- #


def _sandbox(
    tmp_path: pathlib.Path,
    *,
    certbot_present: bool = True,
    crontab_content: str | None = None,
) -> dict:
    """A throwaway filesystem and stubbed commands for the real installer.

    `PREFIX` relocates every destination and the binary check; `SYSTEMCTL` and
    `CRONTAB` are stubs that record how they were called. The sandbox is built
    once and can be handed to `_install()` repeatedly, which is what makes an
    idempotence test mean anything.
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

    # `is-failed` exits 0 when the unit *is* failed, so a stub that returns 0 for
    # everything would claim the renewal service is broken.
    systemctl = stub_dir / "systemctl"
    systemctl.write_text(
        "#!/bin/sh\n"
        f'echo "systemctl $*" >> "{calls}"\n'
        'case "$1" in\n'
        "  is-failed) exit 1 ;;\n"
        "esac\n"
        "exit 0\n"
    )
    systemctl.chmod(0o755)

    crontab_file = tmp_path / "crontab.txt"
    if crontab_content is not None:
        crontab_file.write_text(crontab_content)
    crontab = stub_dir / "crontab"
    crontab.write_text(
        "#!/bin/sh\n"
        f'echo "crontab $*" >> "{calls}"\n'
        'case "$1" in\n'
        f'  -l) if [ -f "{crontab_file}" ]; then cat "{crontab_file}"; else\n'
        '        echo "no crontab for root" >&2; exit 1; fi ;;\n'
        f'  -) cat > "{crontab_file}" ;;\n'
        "esac\n"
        "exit 0\n"
    )
    crontab.chmod(0o755)

    return {
        "prefix": prefix,
        "calls": calls,
        "crontab_file": crontab_file,
        "env": {
            **os.environ,
            "PREFIX": str(prefix),
            "SYSTEMCTL": str(systemctl),
            "CRONTAB": str(crontab),
        },
    }


def _install(sandbox: dict) -> subprocess.CompletedProcess:
    """Run the installer — the real script the deploy runs — in the sandbox."""
    sandbox["calls"].unlink(missing_ok=True)
    return subprocess.run(
        ["sh", str(INSTALLER)],
        capture_output=True,
        text=True,
        timeout=60,
        env=sandbox["env"],
    )


def _calls(sandbox: dict) -> str:
    return sandbox["calls"].read_text() if sandbox["calls"].exists() else ""


def test_installer_installs_the_units_and_enables_the_timer(tmp_path):
    sandbox = _sandbox(tmp_path)
    result = _install(sandbox)
    prefix, calls = sandbox["prefix"], _calls(sandbox)

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
    assert "enable --now certbot-renew.timer" in calls, (
        f"the timer must be enabled and started, calls were:\n{calls}"
    )


def test_installer_runs_the_unit_rather_than_trusting_it(tmp_path):
    """An armed timer is not a working one, and only one of those was ever checked.

    `ExecStart=/usr/local/bin/certbot renew --quiet --dry-run` satisfies every
    file-reading assertion in this module and renews nothing, forever, reporting
    success to journald throughout. So does a broken dns-route53 plugin, a revoked
    IAM key, or certbot's Python being upgraded out from under it. The only way to
    know the unit can renew is to run the unit.
    """
    sandbox = _sandbox(tmp_path)
    result = _install(sandbox)
    calls = _calls(sandbox)

    assert result.returncode == 0, result.stderr
    assert "start --wait certbot-renew.service" in calls, (
        f"the installer must run the service once, in its own environment, rather "
        f"than only enabling it. Calls were:\n{calls}"
    )
    assert "is-failed" in calls, (
        "and must report whether the last run failed: 'armed' and 'working' are "
        "different questions, and only the first was ever asked"
    )


def test_installer_fails_when_the_binary_the_unit_names_is_missing(tmp_path):
    """The check whose absence cost ninety-three days.

    A renewal unit pointing at a binary that is not there is exactly the
    configuration that was live, and it produced no error anywhere. Here it
    fails, before anything is enabled, and the deploy run goes red.
    """
    sandbox = _sandbox(tmp_path, certbot_present=False)
    result = _install(sandbox)

    assert result.returncode != 0, "a missing certbot binary must fail the install"
    assert "certbot" in (result.stderr + result.stdout)
    assert "enable" not in _calls(sandbox), (
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
    sandbox = _sandbox(tmp_path, crontab_content=legacy)
    result = _install(sandbox)

    assert result.returncode == 0, result.stderr
    remaining = sandbox["crontab_file"].read_text()
    assert "certbot" not in remaining, "the legacy renewer must be removed"
    assert "unrelated-job" in remaining, "unrelated crontab entries must survive"

    backups = list((sandbox["prefix"] / "root").glob("crontab.bak.*"))
    assert backups, "back the crontab up before rewriting it"
    assert "certbot renew" in backups[0].read_text()


def test_installer_removes_a_reformatted_renewer_too(tmp_path):
    """The line that caused the outage would survive a match on `certbot renew`.

    An absolute path, a reordered flag, a wrapper — any of them defeats a narrower
    match while still renewing (or failing to renew) behind the timer's back.
    """
    reformatted = "30 2 * * * /usr/local/bin/certbot -q renew\n@daily /bin/true\n"
    sandbox = _sandbox(tmp_path, crontab_content=reformatted)
    result = _install(sandbox)

    assert result.returncode == 0, result.stderr
    remaining = sandbox["crontab_file"].read_text()
    assert "certbot" not in remaining
    assert "/bin/true" in remaining


def test_installer_leaves_the_legacy_renewer_alone_when_it_cannot_arm_the_new_one(tmp_path):
    """A host that cannot run the new mechanism keeps the old one.

    Removing the crontab line before proving the unit works would turn a broken
    install into no renewal at all — worse than the state it found.
    """
    legacy = "0 3 * * * certbot renew --quiet\n"
    sandbox = _sandbox(tmp_path, certbot_present=False, crontab_content=legacy)
    result = _install(sandbox)

    assert result.returncode != 0
    assert "certbot renew" in sandbox["crontab_file"].read_text(), (
        "the legacy renewer must survive a failed install"
    )


def test_installer_succeeds_on_a_host_with_no_crontab(tmp_path):
    """`crontab -l` exits 1 when there is no crontab; that is not an error here."""
    result = _install(_sandbox(tmp_path, crontab_content=None))

    assert result.returncode == 0, result.stderr


def test_installer_running_twice_changes_nothing(tmp_path):
    """Every deploy runs it, so the second run must be a no-op — against the state
    the first one left, not against a fresh filesystem.

    The first version of this test built two independent prefixes and compared a
    file to itself, which proved nothing at all: the path that matters is files
    already present, timer already enabled, crontab already filtered.
    """
    sandbox = _sandbox(tmp_path, crontab_content="0 3 * * * certbot renew --quiet\n@daily /bin/true\n")

    first = _install(sandbox)
    assert first.returncode == 0, first.stderr
    timer_after_first = (sandbox["prefix"] / "etc/systemd/system/certbot-renew.timer").read_text()
    crontab_after_first = sandbox["crontab_file"].read_text()
    backups_after_first = len(list((sandbox["prefix"] / "root").glob("crontab.bak.*")))

    second = _install(sandbox)

    assert second.returncode == 0, second.stderr
    assert (sandbox["prefix"] / "etc/systemd/system/certbot-renew.timer").read_text() == timer_after_first
    assert sandbox["crontab_file"].read_text() == crontab_after_first
    assert len(list((sandbox["prefix"] / "root").glob("crontab.bak.*"))) == backups_after_first, (
        "a second run must not keep writing crontab backups: there is nothing left "
        "to remove, so there is nothing to back up"
    )
    assert "start --wait certbot-renew.service" in _calls(sandbox), (
        "and it must still exercise the unit, which is the check that would have "
        "caught the original defect on any deploy after it appeared"
    )


# --------------------------------------------------------------------------- #
# Detection off the host
# --------------------------------------------------------------------------- #


def _self_signed_server(tmp_path: pathlib.Path, days: int = 30) -> tuple[subprocess.Popen, int]:
    """A throwaway HTTPS listener presenting its own certificate.

    It exists so the two paths that matter most in the expiry check — the day
    comparison and the chain validation — are proven by running them rather than
    by matching text. Neither needs the internet, and neither may depend on
    production being up: a unit test that fails when a website is down teaches
    people to ignore it.
    """
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
         "-keyout", str(key), "-out", str(cert), "-days", str(days),
         "-subj", "/CN=localhost"],
        check=True, capture_output=True, timeout=120,
    )
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    server = subprocess.Popen(
        ["openssl", "s_server", "-accept", str(port), "-cert", str(cert),
         "-key", str(key), "-www", "-quiet"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    else:  # pragma: no cover - the listener never came up
        server.terminate()
        raise AssertionError("the test TLS server never accepted a connection")
    return server, port


def test_expiry_check_fails_a_certificate_inside_the_threshold(tmp_path):
    """The comparison itself, run rather than described.

    Until this existed, inverting `-lt` to `-gt` in the script reddened nothing:
    the threshold was asserted only by reading the default out of the source, and
    the one behavioural test exited twenty lines earlier on an unreadable
    certificate. This is the line the whole detector rests on.
    """
    server, port = _self_signed_server(tmp_path, days=30)
    try:
        result = subprocess.run(
            ["sh", str(EXPIRY_SCRIPT), f"127.0.0.1:{port}", "99999"],
            capture_output=True, text=True, timeout=120,
        )
    finally:
        server.terminate()

    assert result.returncode != 0, (
        "a certificate with fewer days left than the threshold must fail the "
        f"check:\n{result.stdout}{result.stderr}"
    )
    assert "days remaining" in (result.stdout + result.stderr)
    assert "99999" in (result.stdout + result.stderr), (
        "the failure should name the threshold it compared against"
    )


def test_expiry_check_fails_an_untrusted_chain_with_time_to_spare(tmp_path):
    """Dates are not the only way TLS breaks.

    The certificate here has thirty days left, so it passes the day comparison and
    then fails because nothing trusts it — which is the ordering the script needs:
    an expired certificate reports its expiry, and a valid-but-untrusted one
    reports the client failure.
    """
    server, port = _self_signed_server(tmp_path, days=30)
    try:
        result = subprocess.run(
            ["sh", str(EXPIRY_SCRIPT), f"127.0.0.1:{port}"],
            capture_output=True, text=True, timeout=120,
        )
    finally:
        server.terminate()

    assert result.returncode != 0, "an untrusted chain must fail the check"
    assert "verifying client" in (result.stdout + result.stderr), (
        f"and must say so, rather than reporting an expiry problem:\n"
        f"{result.stdout}{result.stderr}"
    )


def test_expiry_check_bounds_the_handshake(tmp_path):
    """A check that hangs reports nothing, which is the failure mode under repair.

    `openssl s_client` has no handshake timeout of its own: a host that completes
    the TCP connection and then says nothing blocks forever. In the deploy workflow
    that would stall a job whose concurrency group is serialized and does not
    cancel in progress, so every later production deploy would queue behind it.
    """
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)  # accepts the connection, then says nothing at all
    port = listener.getsockname()[1]
    try:
        result = subprocess.run(
            ["sh", str(EXPIRY_SCRIPT), f"127.0.0.1:{port}"],
            capture_output=True, text=True, timeout=90,
        )
    finally:
        listener.close()

    assert result.returncode != 0, "a silent host must fail, not pass"
    assert "could not read a certificate" in (result.stdout + result.stderr)


def test_expiry_threshold_sits_inside_the_renewal_window():
    """21 days: renewal starts at 30, so an alert means broken, not merely due.

    A threshold at or above 30 days fires while renewal is still expected to
    happen, which teaches its reader to ignore it; a threshold at 3 days is an
    outage notification. This reads the script's default textually — the live
    behaviour is proven in step 10 against production.
    """
    match = re.search(r"(?i)min_days.*?:-\s*(\d+)", _code(EXPIRY_SCRIPT))
    assert match, "the script must define a default day threshold"

    default_days = int(match.group(1))
    assert 14 <= default_days <= 29, (
        f"the default threshold is {default_days} days; it must leave slack after "
        "renewal's 30-day window opens and before expiry"
    )


def test_expiry_check_validates_the_chain_without_trust_overrides():
    """An expired certificate is only one of the ways TLS breaks."""
    script = _code(EXPIRY_SCRIPT)

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

    checked = set()
    for job in _workflow(EXPIRY_WORKFLOW)["jobs"].values():
        strategy = job.get("strategy") or {}
        matrix = strategy.get("matrix") or {}
        checked.update(matrix.get("host") or [])
        assert strategy.get("fail-fast") is False, (
            "one host failing must not hide the other's state; they share a "
            "certificate today and that is exactly what could change"
        )

    missing = set(PRODUCTION_HOSTS) - checked
    assert not missing, f"{sorted(missing)} served by the same certificate but not checked"

    # A matrix nothing reads is decoration: hardcoding one host in the `run:` line
    # keeps every assertion above green while the apex is never actually checked.
    steps = [
        step
        for job in _workflow(EXPIRY_WORKFLOW)["jobs"].values()
        for step in job["steps"]
    ]
    invocations = [str(step.get("run", "")) for step in steps if "check-tls-expiry.sh" in str(step.get("run", ""))]
    assert invocations, "the workflow must run scripts/check-tls-expiry.sh"
    assert any("matrix.host" in run for run in invocations), (
        f"the check must be given the matrix host, not a hardcoded one: {invocations}"
    )


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

    health = next((i for i, body in enumerate(bodies) if "check-tls-expiry.sh" in body), None)
    assert health is not None, "the deploy should also report certificate health"

    # The job has no checkout of its own historically; the expiry step needs one,
    # and reordering them turns every deploy red with "cannot open ...".
    checkout = next(
        (i for i, step in enumerate(steps) if "actions/checkout" in str(step.get("uses", ""))),
        None,
    )
    assert checkout is not None and checkout < health, (
        "check out the repository before running a script from it"
    )

    # Retried for the same reason the smoke check is: a transient network fault on
    # the runner must not mark a successful production deploy as failed.
    assert re.search(r"for attempt in|seq 1", bodies[health]), (
        "the certificate health step must retry before failing the run"
    )
