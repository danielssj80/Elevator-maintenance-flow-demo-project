# Tasks: harden-tls-renewal

> Read `docs/openspec-tasks-mandatory-steps.md` before editing this file.
>
> **One documented deviation from §3 of that file.** The agent must execute all
> testing itself, and it does — except for steps 13.1–13.4, which require a shell
> on the production instance. This environment has no AWS CLI and no credentials,
> and the instance has no SSH by design (SSM only). Those four sub-steps are
> executed by the operator, who pastes the output into the step 13 report; the
> agent's own substitutes for them are 13.5 and 13.6, which read the same facts
> back out of the deploy workflow and the scheduled check. Every other test in
> this file is agent-executed.

## 0. Setup: Create Feature Branch (MANDATORY)

- [x] 0.1 Create branch `feature/harden-tls-renewal` from `origin/main` (PR #34 is
      merged into `2b5a284`, so this is not stacked on anything)
- [x] 0.2 Verify current branch with `git branch --show-current`
- [x] 0.3 Record the baseline the hand recovery left behind: served certificate
      `notBefore=Sep 13 16:52:29 2026`, `notAfter=Dec 12 16:52:28 2026`, both
      hostnames verifying without `-k`. Everything below is built on a working
      certificate, not an outage

## 1. Incident evidence report

- [x] 1.1 Write `reports/2026-09-13-incident-tls-expiry.md` recording the five
      pieces of evidence: the served certificate's dates, the identical dates on
      disk, `letsencrypt.log`'s last entry (`2026-06-19 18:10`, `Arguments: []`),
      the `PATH` reproduction (`sudo env PATH=/usr/bin:/bin certbot --version` →
      `No such file or directory`), and the live crontab having acquired a `-T`
      that no repository file showed
- [x] 1.2 Record both verification defects in the same report: task 10.6 of
      `deploy-aws-https` accepted an interactive `--dry-run` as evidence for a
      requirement about cron and about the reload, and `production-deployment` is
      the one capability `openspec validate` cannot read

## 2. Guards First — Failing Tests (TDD)

- [x] 2.1 Write `backend/tests/unit/test_tls_renewal_config.py`, asserting the
      properties whose absence caused the outage:
      - the renewal unit's `ExecStart` is an **absolute** path to certbot and the
        file it names is the one the installer checks
      - the timer fires at least twice a day and sets `Persistent=true`
      - the deploy hook passes `exec -T` and is installed under
        `/etc/letsencrypt/renewal-hooks/deploy/`
      - the installer removes any crontab entry invoking certbot, after backing
        the crontab up, and exits non-zero when the certbot binary is missing
      - `deploy.yml` runs the installer **after** its smoke check, and runs the
        expiry check
      - the expiry script's default threshold is between 14 and 29 days — inside
        the renewal window, with slack before expiry
      - `tls-expiry-check.yml` has both a `schedule` and `workflow_dispatch`, and
        covers both hostnames
- [x] 2.2 Run the file and confirm every test is **red** for the right reason
      (the files do not exist yet), capturing the output for the step 9 report

## 3. Renewal Units Under Version Control

- [x] 3.1 `deploy/tls/certbot-renew.service` — `Type=oneshot`,
      `ExecStart=/usr/local/bin/certbot renew --quiet`,
      `After=network-online.target docker.service`
- [x] 3.2 `deploy/tls/certbot-renew.timer` — `OnCalendar=*-*-* 03,15:00:00`,
      `RandomizedDelaySec=3600`, `Persistent=true`, `WantedBy=timers.target`
- [x] 3.3 `deploy/tls/reload-nginx-deploy-hook.sh` — `cd /opt/elevator` then
      `docker compose -f docker-compose.prod.yml exec -T nginx nginx -s reload`,
      mirroring `deploy.yml`'s invocation so the Compose project name is derived
      the same way in both
- [x] 3.4 `deploy/tls/README.md` — what each file is, that the deploy installs
      them, and that editing them on the instance is pointless because the next
      deploy overwrites them
- [x] 3.5 `shellcheck deploy/tls/*.sh` clean — via `shellcheck-py` in the dev
      venv, since the binary is not on this machine and CI does not run it. One
      finding fixed: SC1007 on `CDPATH= cd`

## 4. Installer

- [x] 4.1 `deploy/tls/install-renewal.sh`: `install -m 0644` the unit and timer
      into `/etc/systemd/system/`, `install -m 0755` the hook into
      `/etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh`, then
      `systemctl daemon-reload` and `systemctl enable --now certbot-renew.timer`
- [x] 4.2 Assert the binary named in the unit's `ExecStart` exists and is
      executable; exit non-zero with a named reason if not. This is the check
      whose absence cost 93 days
- [x] 4.3 Remove the legacy renewer: back root's crontab up to
      `/root/crontab.bak.<timestamp>`, filter out lines invoking `certbot renew`,
      install the result. No-op and exit 0 when there is nothing to filter or no
      crontab at all
- [x] 4.4 Print `systemctl list-timers --all certbot-renew.timer` at the end so
      the deploy log carries the next scheduled run
- [x] 4.5 Verify idempotence by running it twice against a temporary root —
      `PREFIX`, `SYSTEMCTL` and `CRONTAB` overrides let the suite run the real
      script against a throwaway filesystem with stubbed commands, in
      `test_installer_running_twice_changes_nothing`. `shellcheck` clean

## 5. Expiry Detection Off the Host

- [x] 5.1 `scripts/check-tls-expiry.sh <host> [min_days]`, default 21: read
      `notAfter` from the certificate the host actually serves, print it, and
      exit non-zero below the threshold
- [x] 5.2 Fail loudly on an unreachable host or an unreadable certificate —
      never pass for want of a date to compare — and assert the chain validates
      with a request that uses **no** `-k`
- [x] 5.3 `.github/workflows/tls-expiry-check.yml` — daily `schedule`, plus
      `workflow_dispatch`, matrix over `elevator.dsaavedra.dev` and
      `dsaavedra.dev` with `fail-fast: false`
- [x] 5.4 Run the script locally against both hostnames; expect a pass with ~90
      days remaining

## 6. Deploy Pipeline Wiring

- [x] 6.1 `deploy.yml`: add an SSM step running
      `sh /opt/elevator/deploy/tls/install-renewal.sh` **after** the smoke check,
      so it can never block or revert an application deploy
- [x] 6.2 `deploy.yml`: add a step running `scripts/check-tls-expiry.sh` for both
      hostnames
- [x] 6.3 Confirm the failure semantics by reading the job graph: installer
      failure turns the run red and leaves the deployed application untouched
- [x] 6.4 Validate the workflow YAML parses and, if available, `actionlint` clean

## 7. Sync the Capability Specs

- [x] 7.1 Sync the deltas into `openspec/specs/` with the sync skill (not by
      hand-editing main specs ahead of it)
- [x] 7.2 Migrate `openspec/specs/production-deployment/spec.md` to the
      `Requirement` / `Scenario` schema: add `## Purpose` and `## Requirements`,
      carry S1–S6, S8 and S9 over as requirements with their WHEN/THEN content
      unchanged, keep `Constraints`, `Files` and `Out of Scope` as trailing
      sections, and replace S7 with this change's requirement
- [x] 7.3 `openspec validate --specs` → **11 passed, 0 failed** (it is 10/1 today)
- [x] 7.4 Diff the migrated spec scenario by scenario against the legacy text and
      record in the step 7 note that no meaning changed outside renewal

## 8. Review and Update Existing Tests (MANDATORY)

- [x] 8.1 Review `backend/tests/unit/test_dev_compose.py` — the precedent this
      new test file follows — for overlap or contradiction
- [x] 8.2 Confirm no existing test asserts the crontab mechanism, so nothing is
      invalidated by removing it; record the grep

## 9. Unit Tests and DB State Verification (MANDATORY)

- [x] 9.1 Capture the pre-test DB baseline (`elevators`, `visit_reports`,
      `telemetry_readings` counts). This change touches no schema and no data;
      the baseline exists to prove that
- [x] 9.2 Targeted run:
      `backend/venv/bin/python -m pytest tests/unit/test_tls_renewal_config.py -v`
- [x] 9.3 Full suite — **ran in CI on PR #35: 245 passed, ruff clean** (run
      `34775209939`). Not runnable here: `tests/conftest.py:43`
      makes a reachable PostgreSQL a session-scoped autouse requirement for every
      test in the suite; Docker Desktop is not running, and the system interpreter
      is 3.14 while the project pins `pydantic==2.10.3` on `python:3.12-slim`.
      `ci.yml` is that environment exactly; evidence goes in the step 13 report
- [x] 9.4 Verify post-test DB state matches the baseline
- [x] 9.5 `ruff check` clean
- [x] 9.6 Create `reports/2026-09-13-step-9-unit-tests.md`

## 10. Endpoint Testing (MANDATORY — AGENT MUST EXECUTE)

> No endpoint changes in this change. The production HTTPS surface **is** its
> subject, so the endpoint tests run against production with a verifying client
> rather than against localhost. No mutating request is made, so no DB state
> restoration is required.

- [x] 10.1 `curl -s https://elevator.dsaavedra.dev/health` (no `-k`) → 200
      `{"status":"ok"}`
- [x] 10.2 `curl -s https://elevator.dsaavedra.dev/api/elevators` → 100 elevators
- [x] 10.3 `curl -s -o /dev/null -w "%{http_code}" https://dsaavedra.dev/` → 200
- [x] 10.4 `curl http://elevator.dsaavedra.dev/` → 301 to the HTTPS URL
- [x] 10.5 `openssl s_client` on both hostnames → issuer Let's Encrypt, SAN
      covering both names, `notAfter` = 2026-12-12
- [x] 10.6 `scripts/check-tls-expiry.sh` on both hostnames → pass
- [x] 10.7 Create `reports/2026-09-13-step-10-endpoint-testing.md`

## 11. E2E Playwright (MANDATORY if frontend changes)

- [x] 11.1 **N/A — no frontend change.** No component, page, route or user
      workflow is touched; the change is host configuration, CI and specs. Record
      the reason here rather than silently skipping the step

## 12. Mutation Checks on Every New Guard (MANDATORY)

> Break each guard, watch it go red, restore it. Inline, one at a time — not as a
> later audit pass.

- [x] 12.1 `ExecStart=certbot renew` (bare, the original bug) → absolute-path test red
- [x] 12.2 Drop `-T` from the deploy hook → TTY test red
- [x] 12.3 `OnCalendar=*-*-* 03:00:00` (once daily) → frequency test red
- [x] 12.4 Remove the crontab-removal block from the installer → single-renewer test red
- [x] 12.5 Remove the missing-binary check from the installer → its test red
- [x] 12.6 Default threshold to 45 days (outside the renewal window) → slack test red
- [x] 12.7 Remove `schedule` from `tls-expiry-check.yml` → scheduling test red
- [x] 12.8 Confirm each mutation reddens the intended test, and create
      `reports/2026-09-13-step-12-mutation-checks.md`. **Two findings:** mutation
      12.2 passed at first — the `exec -T` assertion was satisfied by the comment
      explaining why `exec -T` matters — and the hostname assertion had the same
      defect. Both rewritten to read code and the parsed matrix; 10 mutations, 10
      red. 12.1 reddens five tests because the installer reads the certbot path out
      of the unit, which is the single source of truth working
- [x] 12.9 Two mutations added for the repaired guards (apex host dropped from the
      matrix; verification disabled in the expiry check), plus 12.10 for the deploy
      step order — the first attempt at which was a bad mutation, not a weak guard

## 13. Verification in the Real Configuration

> The step the original change got wrong. Evidence from an interactive shell does
> not count here.
>
> **This section is the archive blocker the independent review raised.** The main
> specs already assert renewal properties that nothing has verified on the host,
> which is defensible while the change is open and is not once it is archived.
> `/archive` does not run until 13.1–13.4 are recorded below.
>
> Note that 13.1 now does more than copy files: the installer runs
> `systemctl start --wait certbot-renew.service`, so a host where renewal cannot
> actually run makes the install fail — and leaves the hand-patched crontab line
> in place rather than removing it.

- [x] 13.1 **(OPERATOR, SSM)** `sudo sh /opt/elevator/deploy/tls/install-renewal.sh`
      after the branch is on the instance — or simply let the post-merge deploy
      run it, which is the path being verified
- [x] 13.2 **(OPERATOR, SSM)** `systemctl list-timers --all certbot-renew.timer`
      → enabled, with a next run; and `sudo systemctl start certbot-renew.service`
      then `journalctl -u certbot-renew -n 30` → certbot executed from the unit's
      own environment and exited 0
- [x] 13.3 **(OPERATOR, SSM)** `sudo /usr/local/bin/certbot renew --dry-run --run-deploy-hooks`
      → simulated renewal succeeds **and the hook runs**; confirm the reload
      landed (`docker compose -f /opt/elevator/docker-compose.prod.yml logs --tail=20 nginx`).
      Plain `--dry-run` does not run deploy hooks — that default is half of why the
      original verification proved nothing
- [x] 13.4 **(OPERATOR, SSM)** `sudo crontab -l` → no certbot line remains, and
      `ls /root/crontab.bak.*` → the backup exists
- [ ] 13.5 **(AGENT)** After merge, read the deploy run with `gh run view --log`
      and confirm the installer step ran and printed the timer's next run
- [ ] 13.6 **(AGENT)** `gh workflow run tls-expiry-check.yml`, then read the run:
      both hostnames pass with the expected days remaining
- [x] 13.7 Create `reports/2026-09-14-step-13-real-configuration.md`, pasting the
      operator output verbatim alongside the agent-collected run logs
- [ ] 13.8 Two findings came out of the real host, both fixed in the repo and both
      about signals a human reads. `journalctl -u certbot-renew` without `sudo`
      prints `-- No entries --` for a unit that ran perfectly, because the SSM user
      is in none of `adm`/`systemd-journal`/`wheel` — silence that reads exactly
      like "renewal never ran". And certbot labels the hook as having "ran with
      error output" because nginx writes its reload notice to stderr, so every
      successful renewal would carry the word "error". Docs corrected; hook now
      redirects `2>&1`. **Confirm after the merge-time deploy re-installs the
      corrected hook:** one `certbot renew --dry-run --run-deploy-hooks` should
      report "ran with output" rather than "ran with error output"
- [ ] 13.9 Close the three outstanding confirmations: `sudo crontab -l`,
      `sudo ls -l /root/crontab.bak.*`, `sudo journalctl -u certbot-renew -n 20`

## 14. Update Technical Documentation (MANDATORY)

- [x] 14.1 `docs/deployment.md` — replace the *TLS Certificate Renewal* section:
      the timer and hook, where they come from, that the deploy installs them,
      how to verify (`systemctl list-timers`, `journalctl -u certbot-renew`,
      `certbot renew --dry-run --run-deploy-hooks`), and the expiry check. Delete
      the crontab line it documents today
- [x] 14.2 `docs/deployment.md` — add the incident to the guide as a named trap:
      cron's `PATH` on AL2023 versus a pip-installed certbot, and that certbot is
      on Python 3.9 with a deadline already past
- [x] 14.3 `docs/api-spec.yml` — no change required (no endpoint added or altered)
- [x] 14.4 `docs/data-model.md` — no change required (no entity or field touched)
- [x] 14.5 `docs/base-standards.md` — proposed, and **approved by the user on
      2026-09-14**, so added to §1 Core Principles as *"Verify in the environment
      it runs in"*, with the incident named as its evidence. This is the seventh
      core principle and the only one that came from an outage
- [x] 14.6 Note every `docs/` file touched in the PR description

## 15. Review, Archive, Commit

- [x] 15.1 `/adversarial-review` in a cold-start session — **FAIL: 1 blocker, 5
      majors, 5 minors, 2 questions.** See
      `reports/2026-09-14-adversarial-review-independent.md`. The first attempt
      died on a rate limit having read only the spec side and was relaunched with
      its budget aimed at the diff
- [x] 15.2 Address every finding, artifacts before code. The two that mattered
      most were invisible from inside: the detector could hang forever (stalling
      every later production deploy behind a serialized concurrency group), and
      nothing ever ran the unit — `ExecStart=... renew --quiet --dry-run` would
      have passed all 13 guards. Also: the idempotence test never ran the
      installer twice, and fixing it exposed a backup filename two runs could
      collide on. Now 19 tests, 9 mutations re-run, 9 red
- [x] 15.2b Re-run of the independent review — **declined by the user on
      2026-09-14**, the corrections being covered by 9 red mutations, 19 tests,
      green CI and the verification on the instance itself
- [x] 15.3 `/archive` — archived 2026-09-14 as `2026-09-14-harden-tls-renewal`
- [x] 15.4 `/commit` → PR #35, ready for review, CI green (251 passed). Merge is
      the operator's call
- [x] 15.5 Registered both follow-ups as Notion tasks under *Backlog
      improvements* on 2026-09-14: [Move the certbot runtime off Python
      3.9](https://app.notion.com/p/3db3ada00a9581cc91eef85ed5e2ada1) (High) and
      [Add a TLS monitor independent of GitHub Actions
      scheduling](https://app.notion.com/p/3db3ada00a95811782c7f292fda2c7ee)
      (Medium)
