# Change: harden-tls-renewal

| | |
|---|---|
| **Status** | Proposed — 2026-09-13 |
| **Milestone** | Unplanned — production incident (certificate expiry, both sites) |
| **Notion task** | Pending — to register under *Backlog improvements* |
| **Branch** | `feature/harden-tls-renewal`, from `origin/main` (`2b5a284`) |
| **Started** | 2026-09-13 |

## Summary

The wildcard certificate for `*.dsaavedra.dev` expired on 2026-09-10 and took
down both `elevator.dsaavedra.dev` and the personal portfolio at `dsaavedra.dev`,
which share one nginx container and one certificate. It had never renewed: the
renewal was a crontab line beginning with a bare `certbot`, and `cronie` runs
jobs with `PATH=/usr/bin:/bin` while the pip-installed binary lives in
`/usr/local/bin`. Ninety-three days, thirty silent failures inside the renewal
window, no signal anywhere.

This change moves the renewal mechanism into version control, has every deploy
re-assert it on the host, and puts the detection off the instance where it can
see what a client sees.

## The evidence, in four lines

```
served + on-disk cert   notBefore=Jun 12 11:29:09 2026   notAfter=Sep 10 11:29:08 2026
letsencrypt.log         last entry 2026-06-19 18:10, Arguments: []   ← a manual run in June
cron-environment repro  sudo env PATH=/usr/bin:/bin certbot --version → No such file or directory
live crontab            carried a -T that no file in this repository ever showed
```

## Why the specification did not catch it

Scenario S7 required that *the cron job runs* and that *nginx reloads*. The task
that closed it ran `certbot renew --dry-run` in an operator's interactive shell —
which uses the operator's `PATH` and, by certbot's default, runs no deploy hook.
It tested neither clause of the requirement it was accepted as evidence for.

And `production-deployment` is the only capability in the repository that
`openspec validate` rejects: legacy `S1…S9` prose, no `## Requirements`, so S7 was
never machine-checkable either. Both are fixed here.

## The three things most likely to waste an afternoon

1. **`certbot renew --dry-run` does not run deploy hooks.** It needs
   `--run-deploy-hooks`. Testing without it proves the renewal and nothing about
   the reload — exactly the gap that produced this outage.
2. **`cronie` on AL2023 has no `/var/log/cron` and the instance has no MTA.** A
   cron job's exit status is genuinely unobservable there. That is why the
   renewal moves to a systemd timer: `journalctl -u certbot-renew` answers the
   question that could not be answered during the incident.
3. **GitHub disables scheduled workflows after 60 days of repository
   inactivity.** The new expiry check is therefore not a monitor with an
   independent lifetime, and `design.md` §4 says so rather than implying
   otherwise.

## What this deliberately does not fix

certbot 4.2.0 is running on Python 3.9, which boto3 stopped supporting in April
2026 and certbot is about to drop. Renewal will break again when either is
upgraded — with 21 days of warning now instead of none. Moving the certbot
runtime is a separate change with its own verification. The static IAM keys in
`/root/.aws/credentials` also stay: `design.md` §6 explains why routing DNS-01
through the instance role would widen the path from the public backend to Route 53
more than it would improve credential hygiene.

## Artifacts

- [proposal.md](./proposal.md)
- [design.md](./design.md)
- [tasks.md](./tasks.md)
- [specs/production-deployment/spec.md](./specs/production-deployment/spec.md)
- [specs/deploy-pipeline/spec.md](./specs/deploy-pipeline/spec.md)
