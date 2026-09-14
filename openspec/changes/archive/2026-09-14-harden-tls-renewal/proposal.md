# Proposal: harden-tls-renewal

## Why

On 2026-09-13 both `https://elevator.dsaavedra.dev` and `https://dsaavedra.dev`
began failing TLS verification. The certificate nginx was serving was the
**original** one, issued on 2026-06-12 during `deploy-aws-https`:

```
notBefore=Jun 12 11:29:09 2026 GMT
notAfter =Sep 10 11:29:08 2026 GMT   ← 3 days before the outage was noticed
SAN: *.dsaavedra.dev, dsaavedra.dev
```

It had never been renewed. Not once in 93 days. The certificate **on disk** was
the same original, and the last entry in `/var/log/letsencrypt/letsencrypt.log`
was `2026-06-19 18:10` with `Arguments: []` — a `certbot certificates` typed by
hand. Certbot had not executed since June. The renewal window had been open
since 2026-08-11 and produced 30 consecutive silent failures.

The root cause, reproduced exactly rather than inferred:

```
$ sudo env PATH=/usr/bin:/bin certbot --version
env: 'certbot': No such file or directory
```

`cronie` runs jobs with `PATH=/usr/bin:/bin`. `deploy-aws-https` installed
certbot with `pip3 install certbot certbot-dns-route53`, which puts it in
`/usr/local/bin/certbot`, and specified the renewal as a crontab line beginning
with a **bare `certbot`**. Every night at 03:00 the line exited 127 on its first
word and the `&&` swallowed everything after it. Silent twice over: `--quiet`,
and Amazon Linux 2023 ships no MTA, so cron's mail to root went nowhere.

**The specification claimed this was verified.** Scenario S7 requires *"when the
certbot renewal cron job runs, certbot renew completes successfully and nginx
reloads with the renewed certificate"*. The task that closed it, `10.6`, ran
`certbot renew --dry-run` — in the operator's interactive shell, with the
operator's `PATH`, and (by certbot's own default) without executing any deploy
hook. It exercises neither half of the requirement it was accepted as evidence
for. Worse, `production-deployment` is the **only capability in this repository
that `openspec validate` rejects**: it is still in the legacy `S1…S9` prose
format with no `## Requirements` section, so S7 has never been machine-checkable
either.

Nothing else in the system could have caught it. The only check anywhere that
fails on an expired certificate is `deploy.yml`'s smoke step (`curl -sf`), and
it runs only on a merge to `main`. The last deploy before the outage was
2026-08-31, ten days before expiry; nothing ran inside the window. Monitoring
was explicitly *out of scope* in the original change.

Service was restored by hand on 2026-09-13 (renewed at 16:52 UTC, valid to
2026-12-12, both hostnames verifying) and the crontab line now carries an
absolute path. That is a patch on unversioned host state. This change is what
makes the failure non-repeatable: **the mechanism moves into version control and
the detection moves off the host.**

## What Changes

- **Renewal becomes three files in the repository** under `deploy/tls/`: a
  `certbot-renew.service` whose `ExecStart` is an absolute path, a
  `certbot-renew.timer` that runs twice daily with `Persistent=true`, and the
  nginx reload as a **certbot deploy hook**.
- **The reload stops being a shell `&&`.** Installed into
  `/etc/letsencrypt/renewal-hooks/deploy/`, it runs only when a certificate was
  actually renewed, it runs no matter who invoked certbot (timer, operator, or a
  future mechanism), and its failure is reported by certbot instead of by nobody.
  It passes `exec -T`, because there is no TTY in a timer either.
- **`deploy/tls/install-renewal.sh`, run by `deploy.yml` on every deploy.**
  Idempotent. This is the part that matters: host configuration stops being
  something typed once into an SSM session and becomes something every deploy
  re-asserts, so an instance rebuild cannot silently lose it. It also removes the
  legacy crontab line, so there is exactly one renewer rather than two racing.
- **Detection that does not live on the host**: `scripts/check-tls-expiry.sh`
  plus a scheduled `.github/workflows/tls-expiry-check.yml` that runs daily
  against both hostnames, asserts the chain validates, and fails below 21 days
  remaining. It inspects the **served** certificate, not the file on disk —
  the one observation that catches both this outage and the different outage
  where renewal succeeds and the reload does not.
- **`deploy.yml` runs the same check** after its smoke step, so a deploy also
  reports certificate health.
- **`backend/tests/unit/test_tls_renewal_config.py`**: guards that fail against
  the configuration of 12 June. A bare `certbot` in the unit, a missing `-T`, a
  once-daily timer, an unscheduled workflow, a threshold with no slack before
  expiry — each is a red test.
- **`production-deployment` migrated to the `Requirement` / `Scenario` format**
  so the capability validates like every other one, with the renewal requirement
  rewritten to be verifiable and the other scenarios carried over unchanged in
  meaning.
- **`docs/deployment.md` rewritten** where it describes renewal. It currently
  documents the broken cron line — and documents it *without* the `-T` the live
  crontab actually had, which is its own evidence that unversioned host state
  drifts from the repository.

## Capabilities

### Modified Capabilities

- `production-deployment` (delta in `specs/production-deployment/spec.md`): the
  certificate-renewal requirement is rewritten from "a cron job exists" to
  properties that can be checked — the renewal runs from a unit under version
  control, invoked with an absolute path, verified under the environment it
  actually runs in; the reload is bound to the renewal rather than to a shell
  operator; and expiry is detected from outside the host before it happens. A
  new requirement covers that detection. The capability is also migrated to the
  schema-valid format; no other requirement's meaning changes.
- `deploy-pipeline` (delta in `specs/deploy-pipeline/spec.md`): the deploy
  re-asserts host-level renewal configuration and reports certificate health,
  without either being able to block the application deploy.

## Impact

- **New files**: `deploy/tls/certbot-renew.service`,
  `deploy/tls/certbot-renew.timer`,
  `deploy/tls/reload-nginx-deploy-hook.sh`, `deploy/tls/install-renewal.sh`,
  `deploy/tls/README.md`, `scripts/check-tls-expiry.sh`,
  `.github/workflows/tls-expiry-check.yml`,
  `backend/tests/unit/test_tls_renewal_config.py`.
- **Modified files**: `.github/workflows/deploy.yml` (install step + expiry
  check), `docs/deployment.md`, `openspec/specs/production-deployment/spec.md`
  (at sync time).
- **Host state changed**: `/etc/systemd/system/certbot-renew.{service,timer}`
  created and enabled; `/etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh`
  created; root's crontab loses its `certbot renew` line (backed up first).
- **Not modified**: `docker-compose.prod.yml`, `nginx/prod.conf`. The
  certificate paths, the mount and the TLS configuration are all correct and
  were never part of the failure.
- **Backend / frontend / database**: no application code, no schema change, no
  endpoint change. The mandatory Playwright step is N/A and says so.
- **Cost**: none. Two GitHub Actions minutes a day.

## What this does not claim

- **It does not remove the single points of failure.** Renewal still depends on
  one EC2 instance, one Route 53 hosted zone, and one long-lived IAM access key
  pair in `/root/.aws/credentials`. Those keys are now known to work — the
  post-incident `--dry-run` proved it — but nothing rotates them, and nothing
  here changes that. The expiry check turns their eventual failure into a
  21-day warning instead of an outage. It renews nothing itself.
- **certbot 4.2.0 is running on Python 3.9**, which certbot warns it is about to
  drop and for which boto3 ended support in April 2026. A future upgrade of
  either will break renewal. Deliberately **not** fixed here: moving the certbot
  runtime is a separate change with its own verification, and this one is the
  fix for an outage in progress. Recorded as follow-up, not as an oversight.
- **The detector has its own silent failure mode.** GitHub disables scheduled
  workflows after 60 days of repository inactivity. The mitigations are that
  `deploy.yml` runs the same script, that the workflow accepts
  `workflow_dispatch`, and that 60 quiet days on this repository would be
  unusual — not that the problem is solved.
