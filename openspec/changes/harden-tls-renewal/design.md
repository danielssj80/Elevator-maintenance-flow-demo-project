# Design: harden-tls-renewal

## 1. What actually broke, and what it implies for the design

Three facts from the incident, each of which constrains the solution:

| Fact | Implication |
|---|---|
| The invocation worked when typed by the operator and failed under cron's `PATH` | Verification must run in the environment the mechanism runs in, never in a shell |
| The mechanism existed only as a crontab line on the host | It must live in the repository and be re-asserted by something that runs regularly |
| 30 nights of failure produced no signal anywhere | Detection must be outside the host, and must look at what clients see |

Everything below follows from those three rows. Nothing here is a preference
about systemd or about YAML.

## 2. Renewal: a systemd timer, in the repository

`/etc/systemd/system/certbot-renew.service` and `.timer`, both shipped as
`deploy/tls/*` and installed by the deploy.

```ini
# certbot-renew.service
[Service]
Type=oneshot
ExecStart=/usr/local/bin/certbot renew --quiet
```

```ini
# certbot-renew.timer
[Timer]
OnCalendar=*-*-* 03,15:00:00
RandomizedDelaySec=3600
Persistent=true
```

Four decisions in those six lines:

- **Absolute `ExecStart`.** This is the bug. systemd *requires* an absolute path
  in `ExecStart`, so the class of failure that caused this outage cannot be
  expressed in a unit file at all. That property — not systemd's ergonomics — is
  the reason for the migration.
- **Twice daily**, which is what Let's Encrypt asks of every client, with
  `RandomizedDelaySec=3600` so the two requests are not on the hour. A single
  daily attempt gives one chance per day within a 30-day window; two give sixty
  chances, and the first success ends it.
- **`Persistent=true`.** A missed trigger runs on next boot. The instance is a
  `t3.micro` that has been rebooted before; a cron line has no equivalent.
- **`--quiet`, still.** Output is not the signal here — journald records every
  invocation and its exit status, `systemctl list-timers` records the last and
  next run, and the expiry check is what actually watches the outcome.

### Why not simply keep the corrected crontab line

It works — `sudo env -i PATH=/usr/bin:/bin /usr/local/bin/certbot renew --dry-run`
passes on the instance today. It is still the wrong answer, because it is
unversioned host state that no deploy re-asserts, no test can see, and no
instance rebuild reproduces. And on this host cron is the weaker of the two
mechanisms for observability specifically: AL2023 has no `/var/log/cron` and no
MTA, so a cron job's exit status is genuinely unobservable, which is exactly how
30 failures went unnoticed. `journalctl -u certbot-renew` answers the question
that could not be answered during the incident: *did it run, and what did it
return?*

### The installer removes the crontab line

Two renewers are worse than one. Certbot's own lock file makes a collision safe,
but duplicate renewal attempts consume Let's Encrypt quota and, more
importantly, leave the next person unable to tell which mechanism is live. The
installer backs up root's crontab to `/root/crontab.bak.<timestamp>` before
filtering the `certbot renew` line out of it.

## 3. The reload: a certbot deploy hook, not a shell operator

```sh
# /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
cd /opt/elevator
exec docker compose -f docker-compose.prod.yml exec -T nginx nginx -s reload
```

- **In `renewal-hooks/deploy/`, not `--deploy-hook` on the command line.**
  Certbot runs every executable in that directory after a successful renewal,
  whatever invoked certbot. The reload therefore cannot be lost by someone
  running `certbot renew` by hand, which is precisely what happened during the
  incident recovery.
- **Bound to an actual renewal.** `certbot renew` exits 0 both when it renews and
  when nothing is due, so the original `&&` fired a reload every night and could
  not distinguish a failed reload from a no-op. A deploy hook runs only on
  renewal and its failure is certbot's error, logged in `letsencrypt.log`.
- **`exec -T`.** There is no TTY in a timer any more than in cron. The live
  crontab had acquired the `-T` that `design.md` and `docs/deployment.md` never
  showed; shipping the hook from the repository is what stops that divergence
  from recurring.
- **`cd /opt/elevator` then a relative `-f`**, mirroring `deploy.yml` exactly, so
  the Compose project name is derived identically in both places and `exec`
  cannot fail to find the container because one of them named the project
  differently.
- **It fails loudly.** If nginx is down when a renewal lands, the hook fails, the
  renewal stays done, and nginx keeps serving the old certificate until it is
  recreated. Certbot will not re-run the hook, because nothing is due any more.
  This residual hole is real and is the reason §4 checks the served certificate
  rather than the file.

## 4. Detection: the served certificate, from outside

`scripts/check-tls-expiry.sh <host> [min_days]` opens a TLS connection, reads
`notAfter` from the certificate the server actually presents, and fails below the
threshold. It also runs a verifying request (`curl` with no `-k`), so an expired,
mismatched or incomplete chain fails even if the dates read fine.

Three deliberate choices:

- **Served, not on disk.** A file check passes in the one scenario §3 leaves
  open: renewed on disk, stale in nginx's memory. Only a client's view catches
  both failures, and a client's view is what the outage was.
- **Off the host.** A checker on the instance cannot report that the instance is
  unreachable. Running it in GitHub Actions also means the alert channel already
  exists: a failing scheduled run notifies the account that owns the workflow.
- **21 days.** Certbot renews at 30 days remaining. A 21-day threshold leaves 9
  days in which renewal should already have happened, so an alert means "the
  mechanism is broken", not "renewal is due" — a threshold that fires while
  renewal is still expected to run trains its reader to ignore it.

Both hostnames are checked. They share one wildcard certificate and one nginx
today, and asserting that per host is how a future split is caught rather than
assumed.

### The detector's own failure mode, stated rather than hidden

GitHub disables scheduled workflows after 60 days without repository activity.
So the check is *not* a monitor with an independent lifetime. Mitigations:
`deploy.yml` runs the same script on every deploy, the workflow accepts
`workflow_dispatch`, and the script runs locally. A real monitor (an external
uptime service with TLS expiry alerting) is the right long-term answer and is
recorded as follow-up rather than pretended here.

## 5. The deploy re-asserts the host configuration

`deploy.yml` gains one SSM step that runs `deploy/tls/install-renewal.sh` from
the checkout already at `/opt/elevator`, plus one step that runs the expiry
check. Placement and failure semantics:

- **After the smoke check.** A broken renewal install must never prevent the
  application from deploying; a deploy that has already succeeded is not rolled
  back by it.
- **It still turns the run red.** The installer exits non-zero if the certbot
  binary named in `ExecStart` is absent or not executable, or if enabling the
  timer fails. The alternative — warn and pass — is how the original failure
  survived 30 nights.
- **Idempotent.** Files are installed with `install -m`, `daemon-reload` and
  `enable --now` are re-run each time, and the crontab filter is a no-op once
  there is nothing to filter. Running it on every deploy is the point: it heals
  drift instead of documenting it.

SSM `AWS-RunShellScript` already runs as root on this instance, which is why the
installer needs no privilege handling of its own.

## 6. Rejected: moving DNS-01 auth to the instance role

It was the obvious cleanup — the instance already has `elevator-ssm-role`, and
`/root/.aws/credentials` holds long-lived static keys for the `certbot-route53`
IAM user. It is rejected here, for two reasons.

**Blast radius.** `route53:ChangeResourceRecordSets` on the role the public
backend assumes means an application compromise can rewrite the DNS of both
sites, including pointing them at someone else's host and passing a domain
validation there. Today those keys are readable only by root on an instance with
no SSH and no shell exposure, and their single hosted-zone scope is enforced on a
principal the application cannot assume. Trading a credential-hygiene
improvement for a wider path from the internet to DNS is the wrong trade.

**It was not the cause.** The post-incident `--dry-run` succeeded, so the
credentials work. Rebuilding the authentication path inside the change that fixes
a `PATH` bug would enlarge the surface being verified for no defect found.

The genuine weakness — nothing rotates those keys and nothing notices if they are
revoked — is answered from the other end: a revoked key fails renewal, and
renewal failure is what §4 now detects with 9 days to spare.

## 7. Where the files live

- `deploy/tls/` — new directory, for artifacts that configure the **host** rather
  than a container. Neither `nginx/` (container configuration, mounted) nor
  `scripts/` (developer-run helpers) is that. Its `README.md` states that
  everything in it is installed by the deploy and must not be edited on the
  instance.
- `scripts/check-tls-expiry.sh` — belongs with the developer-runnable scripts
  because it is one: it takes a hostname, it is what CI calls, and it is what a
  human runs when they want to know.
- `backend/tests/unit/test_tls_renewal_config.py` — follows the precedent of
  `backend/tests/unit/test_dev_compose.py`, which already asserts properties of
  repository-level infrastructure files from the backend suite. Adding a second
  test runner for four assertions would cost more than it explains.

## 8. Spec format migration

`production-deployment` is the only capability `openspec validate` rejects, for
lack of `## Purpose` and `## Requirements`. Its nine scenarios become
requirements, each keeping at least one `#### Scenario:` block whose WHEN/THEN
content is carried over unchanged; `Constraints`, `Files` and `Out of Scope` are
preserved as trailing sections.

Only the renewal requirement changes meaning, and the delta declares exactly
that: `## MODIFIED Requirements` for renewal, `## ADDED Requirements` for expiry
detection. The other eight are **not** restated as `ADDED` — they are not new,
and a delta that lists them would misrepresent what this change does to a reader
of the archive. The reformat is recorded here and in `tasks.md`, where a
line-by-line comparison is a task with an artifact.

## 9. Out of scope

- Moving the certbot runtime off Python 3.9 (follow-up).
- An external uptime/TLS monitor independent of GitHub Actions (follow-up).
- Rotating or re-scoping the `certbot-route53` credentials (§6).
- Automating the one-time bootstrap of a *new* instance (certbot install,
  first `certonly`, credentials). This change hardens renewal on the instance
  that exists; full provisioning-as-code is a different change.
- Any change to nginx, TLS parameters, HSTS, the certificate's names, or the
  Compose stack.
