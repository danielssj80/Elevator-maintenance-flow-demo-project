# Adversarial Review — Independent Session

- Date: 2026-09-14
- Change: harden-tls-renewal
- Reviewer: independent cold-start session, no prior context, read-only
- Verdict: **FAIL** — 1 blocker, 5 majors, 5 minors, 2 questions
- Status after this round: **all findings addressed; the blocker is a gate, not a
  code change**

The first attempt at this review died on a rate limit after reading only the spec
side; it was relaunched with its effort budget pointed at the diff. Worth
recording, because the findings below came almost entirely from the
implementation, and a review that had spent its budget on prose would have
produced a much weaker report.

## Blocker

**The specification was synced ahead of the host.** Commit `5155e57` put the new
renewal requirement into `openspec/specs/production-deployment/spec.md` while
`install-renewal.sh` has never run on the instance: the timer does not exist
there, root's crontab still holds the hand-patched line from the recovery, and the
deploy hook has never fired. The scenarios *"Renewal succeeds under the
scheduler's environment"* and *"A renewed certificate reaches the running web
server"* have no evidence.

**Disposition: accepted as a gate on archiving, not reverted.** The sync was
deliberate — it is what turned the repository's spec validation from 10/1 to
11/11 — and the delta is accurate about intent. What must not happen is archiving,
which would convert an unverified claim into settled history. Tasks 13.1–13.4 stay
open and `/archive` does not run until their output is recorded. The reviewer's
closing line is the right summary: the first execution of `install-renewal.sh`
should not be unattended, as root, on production.

## Majors

**1. The detector could hang forever.** `openssl s_client` has no handshake
timeout, so a host that completes the TCP connection and then says nothing blocks
indefinitely — the reviewer verified it with a silent listener (`timeout 8` killed
it at 8s). In `deploy.yml` that stalls a job whose concurrency group is
`production-deploy` with `cancel-in-progress: false`, so **every subsequent
production deploy would queue behind a check that never returns**. The sharpest
finding in the report: a monitor whose failure mode is silence, inside the change
whose entire purpose is ending silent failure.

*Fixed:* `timeout 15` around the handshake, `timeout-minutes` on both jobs, a new
behavioural test that points the script at a silent listener and requires it to
fail, and a spec clause requiring the check to be bounded.

**2. Nothing ever ran the unit.** `ExecStart=/usr/local/bin/certbot renew --quiet
--dry-run` would have passed all 13 guards and the installer's own check, renewing
nothing for the life of the instance while journald reported success. Same for a
broken `dns-route53` plugin, a revoked IAM key, or certbot's Python being upgraded
out from under it. The installer proved a path was executable and called it a
renewal mechanism.

*Fixed:* the installer runs `systemctl start --wait certbot-renew.service` and
propagates the status — cheap, because `certbot renew` exits 0 without contacting
ACME when nothing is due — and reports `is-failed` afterwards. It runs **before**
the legacy crontab renewer is removed, so a host that cannot renew keeps whatever
was renewing before. New guard, and the mutation that deletes the run goes red.

**3. The certificate-health step failed the run with no retries**, where the
adjacent smoke check retries 12×10s for exactly this reason. A transient runner
fault would have marked a successful production deploy as failed.

*Fixed:* three attempts with a 10s pause, and the failure semantics are now
specified in the `deploy-pipeline` delta rather than left to the reader.

**4. Spec overstated the code on crontab removal.** *"No crontab entry invoking
certbot remains on the host"* while the code removed only root's-crontab lines
containing the literal `certbot renew` — `certbot -q renew`, `/etc/cron.d/*`,
`/etc/crontab` and other users' crontabs all survived.

*Fixed from both ends:* the match is now on `certbot`, so the line that caused the
outage cannot survive reformatting, and the spec says root's crontab and the
system timers, explicitly disclaiming the rest. New guard for a reformatted
renewer.

**5. `test_installer_running_twice_changes_nothing` never ran the installer
twice.** It built two independent prefixes and compared the timer file to itself.
The idempotence scenario in the `deploy-pipeline` delta was unproven — the same
declaration-versus-behaviour shape as the two guards repaired in step 12.

*Fixed:* the sandbox is built once and the installer invoked repeatedly against
the state the previous run left. That immediately exposed something else: the
mutation making the installer back up on every run **stayed green**, because the
backup filename had second granularity and both runs landed on the same path. A
backup a later run can overwrite is not a backup, so the name now carries the PID
too — and the mutation reddens.

## Minors, all fixed

- **The threshold comparison had no behavioural guard.** Inverting `-lt` to `-gt`
  reddened nothing: the default was asserted by regex, and the one behavioural
  test exited twenty lines earlier. Now a throwaway `openssl s_server` with its own
  certificate is checked against `min_days=99999`, and the day comparison moved
  ahead of the request so an expiry problem reports as one. Two more behavioural
  tests came from the same fixture, and the script gained `host[:port]` so they can
  address it.
- **Nothing asserted the workflow passes `${{ matrix.host }}`** to the script;
  hardcoding one host kept every matrix assertion green while the apex went
  unchecked. Guarded, and the mutation reddens.
- **Nothing guarded that `actions/checkout` precedes the expiry step**, which
  would have turned every deploy red with "cannot open scripts/check-tls-expiry.sh".
  Guarded.
- **Three loose ends in `deploy.yml`:** the install step polled 40×5s against a
  600s `executionTimeout`, so a slow success reported failure; an empty
  `COMMAND_ID` from a rejected `send-command` burned the whole window; and the
  appended `actions/checkout@v4` pinned no `ref`, so on a `workflow_run` event it
  resolved to the default-branch head rather than the SHA being deployed. All
  three fixed.
- **Docs:** the incident write-up was cited at an `openspec/changes/archive/` path
  that does not exist until archiving, and `date -u -d` is GNU-only. Both corrected.

## Questions

**`nginx -s reload` exits 0 once the signal is sent.** The reviewer checked this
and found it largely unfounded — the signalling process parses the configuration
itself and exits non-zero on error, so a broken co-located `portfolio.conf` *is*
caught — leaving only a master-side reconfigure failure as a silent window.

*Accepted knowingly, and now written down* in `design.md` §3 rather than implied
away. That window is covered by the served-certificate check, which is the reason
§4 looks at what clients get instead of at the file.

**The hook took no `flock /opt/deploy.lock`**, which `deploy-pipeline` requires
around Docker-state mutation on the shared nginx. A renewal landing mid-recreation
would lose its reload permanently.

*Fixed:* the hook takes the lock with a bounded wait. New guard.

## What the reviewer checked and found unfounded

Recorded because these were the author's load-bearing assumptions and they held:
the Compose project name is `elevator` in both the deploy and the hook (no `name:`
in the file, both use `cd /opt/elevator` with a relative `-f`), so `exec` finds the
container and the portfolio override cannot change it; the hook's Compose call
resolves under an empty environment (`${IMAGE_TAG:-latest}` has a default,
`env_file` is absolute); `/etc/letsencrypt` is bind-mounted as a directory, so a
renewed certificate and its repointed symlink are visible inside the container;
`crontab -l`'s exit 1 on a crontab-less host is handled and unrelated entries
survive; `|| true` correctly covers the `grep -v` that matches nothing;
partial-failure ordering never leaves the host worse than it was found; the `sed`
extraction of `ExecStart` is correct for this file; an already-expired certificate
exits non-zero. The reviewer also confirmed the format migration lost nothing: the
only legacy assertion dropped is S7's *"`certbot renew --dry-run` succeeds at any
time"*, which is the declared deliberate rewrite.

## After this round

- 19 tests passing (was 13): 6 new guards, 2 repaired.
- 9 mutations re-run, 9 red — including the one that exposed the backup-filename
  collision.
- `shellcheck` and `ruff` clean; `openspec validate --specs` 11/11; the change
  validates `--strict`.
- Archiving remains **blocked** on tasks 13.1–13.4.

## The measurement, again

This project's own note says independent review beats self-review, 7 findings to
3. This round: **13 findings from the cold session**, five of them changing
behaviour, two of them defects in guards the author had already mutation-tested.
The two that matter most were invisible from inside: a monitor that could hang
forever, and a mechanism nothing had ever run.
