# Step 13 Report — Verification in the Real Configuration

- Date: 2026-09-14
- Change: harden-tls-renewal
- Executed by: the operator, over AWS SSM on the production instance
  (`i-01b732fefb1dd6303`). The agent has no AWS credentials in its environment and
  the instance has no SSH by design; this is the documented deviation from
  `docs/openspec-tasks-mandatory-steps.md` §3, recorded at the top of `tasks.md`.
- Branch state on the instance: `deploy/tls` and `scripts/check-tls-expiry.sh`
  checked out from `FETCH_HEAD` of `feature/harden-tls-renewal` at commit
  `a5a63dc`, before the merge — deliberately, so the first execution of
  `install-renewal.sh` was attended rather than unattended as root on production,
  which is what the independent review asked for. The next deploy re-asserts the
  same files from `main`.

## 13.1 — Install

```
$ sudo sh deploy/tls/install-renewal.sh
Created symlink /etc/systemd/system/timers.target.wants/certbot-renew.timer → /etc/systemd/system/certbot-renew.timer.
install-renewal: certbot-renew.service ran from its own unit environment
install-renewal: removed the legacy crontab renewer (backup: /root/crontab.bak.20260914T045652Z.3213611)
NEXT                        LEFT     LAST PASSED UNIT                ACTIVATES
Mon 2026-09-14 15:49:22 UTC 10h left -    -      certbot-renew.timer certbot-renew.service
install-renewal: ok
```

Four things are proven by those six lines:

1. **The unit ran, from its own environment.** This is the guard the adversarial
   review demanded and the one thing the original change never did: an
   `ExecStart` that resolves to nothing, a broken plugin or a revoked credential
   would have failed here. It did not.
2. **The legacy crontab renewer is gone**, and its backup filename carries the PID
   — the fix for the collision that the step-12 mutation exposed, working on the
   real host.
3. **The timer is armed**, with a next run at 15:49:22 UTC. `OnCalendar` is
   `03,15:00:00`; the 49 minutes are `RandomizedDelaySec=3600` doing its job. The
   03:00 trigger had already passed before installation.
4. **`install-renewal: ok` with no `is-failed` warning**, so the service is not in
   a failed state — the second of the two questions ("armed?" and "working?") that
   the outage went unnoticed for want of anyone asking.

`LAST` and `PASSED` read `-` because the *timer* has not fired yet. A run started
with `systemctl start` does not set them, so `-` there is not evidence either way.

## 13.2 — Timer state and journal

```
$ systemctl list-timers --all certbot-renew.timer
Mon 2026-09-14 15:49:22 UTC 10h left -    -      certbot-renew.timer certbot-renew.service

$ journalctl -u certbot-renew -n 30
Hint: You are currently not seeing messages from other users and the system.
      Users in groups 'adm', 'systemd-journal', 'wheel' can see all messages.
-- No entries --
```

**A finding, and it is fixed in this change.** The SSM shell user is in none of
those groups, so `journalctl` without `sudo` reports `-- No entries --` for a unit
that had just run successfully. `design.md` §2 argues for the timer partly because
`journalctl -u certbot-renew` answers the question cron could not — *did it run,
and what did it return?* — and the command as documented answered it with silence
that reads exactly like "renewal has never run".

That is the same class of misreadable signal as the outage itself. `sudo` is now
required on that line in `docs/deployment.md` and `deploy/tls/README.md`, with the
trap spelled out, and the `LAST`/`PASSED` caveat above with it.

## 13.3 — The renewal and the hook, exercised together

```
$ sudo /usr/local/bin/certbot renew --dry-run --run-deploy-hooks
Saving debug log to /var/log/letsencrypt/letsencrypt.log
Python 3.9 support will be dropped in the next planned release of Certbot - please upgrade your Python version.
Processing /etc/letsencrypt/renewal/dsaavedra.dev.conf
/usr/local/lib/python3.9/site-packages/boto3/compat.py:89: PythonDeprecationWarning: Boto3 will no
longer support Python 3.9 starting April 29, 2026. ...
Simulating renewal of an existing certificate for dsaavedra.dev and *.dsaavedra.dev
Hook 'deploy-hook' ran with error output:
 2026/09/14 04:57:32 [notice] 31#31: signal process started

Congratulations, all simulated renewals succeeded:
  /etc/letsencrypt/live/dsaavedra.dev/fullchain.pem (success)
```

**The clause that was never tested is now tested.** `--run-deploy-hooks` made
certbot execute the hook, and `[notice] 31#31: signal process started` is nginx
inside the container acknowledging the reload — with no TTY, through
`flock /opt/deploy.lock`, from a process certbot spawned. The original
verification's plain `--dry-run` runs no hook at all, which is precisely how a
requirement about reloading nginx was closed without ever reloading nginx.

The DNS-01 credentials also work, incidentally: a simulated renewal for a wildcard
name cannot succeed without a Route 53 write.

**A second finding, also fixed.** Certbot labels any hook that wrote to stderr as
having *"ran with error output"*, and nginx writes its reload notice to stderr — so
every successful renewal from now on would have been logged with the word "error"
in the one mechanism whose failures already went unnoticed for three months. The
hook now redirects `2>&1`; the exit status still decides success, only the label
changes. **The instance is running the version without that redirect**; it is the
same command with the same semantics, and the next deploy re-installs the corrected
file.

## 13.4 — One renewer, and the backup

```
$ sudo crontab -l
(no output — the certbot line was the only entry, so the crontab is now empty)

$ ls -l /root/crontab.bak.*
ls: cannot access '/root/crontab.bak.*': Permission denied
```

No entry invoking certbot remains in root's crontab, which is what the scenario
requires. The `ls` failed because `sudo` applied only to the preceding command in
that line — the operator's copy of the instruction, not a property of the host; the
backup path is named in the installer's own output above.

**Still to confirm** (three lines, recorded here when they come back):

```bash
sudo crontab -l; echo "exit: $?"
sudo ls -l /root/crontab.bak.*
sudo journalctl -u certbot-renew -n 20 --no-pager
```

## 13.5 / 13.6 — Post-merge

Open by construction: `deploy.yml`'s new steps run on a merge to `main`, and
`tls-expiry-check.yml` can only be dispatched once it exists on the default branch.
The agent executes and records both.

## Outcome

PASS for 13.1–13.3 and for the substance of 13.4, with two findings from the real
host that no amount of local testing would have produced — both about signals a
human reads, which is the failure mode this change exists to address. The archive
blocker the independent review raised is discharged: the mechanism has now run on
the instance it was written for.
