# Deployment Guide

The application is deployed to AWS EC2 at **https://elevator.dsaavedra.dev**.

---

## Infrastructure

| Component | Detail |
|---|---|
| Instance | EC2 t3.micro, Amazon Linux 2023, eu-north-1 (`i-01b732fefb1dd6303`) |
| Access | AWS SSM Session Manager (no SSH, no port 22) |
| Security Group | Inbound TCP 80 + 443 only |
| DNS | Route 53 A record `elevator.dsaavedra.dev` → Elastic IP |
| TLS | Let's Encrypt wildcard `*.dsaavedra.dev` via DNS-01 + Route 53 |
| App directory | `/opt/elevator/` |
| Secrets | `/etc/elevator/.env` (`chmod 600`, never committed) |

---

## What is deliberately not deployed

**The orchestration tier (n8n, Redis, the worker) runs locally only.** There is
no orchestrator on this instance: `docker-compose.prod.yml` defines none, and
`backend/tests/unit/test_dev_compose.py::test_prod_compose_defines_no_orchestrator`
fails if one is ever added.

Two reasons, both load-bearing. n8n holds a model-provider credential, and this
stack auto-deploys on merge to the default branch, so an orchestrator here would
put a scheduler with credentials on a public host. And the endpoints it drives —
`POST /api/telemetry/readings` and `POST /api/inference/run` — are not registered
in production at all, so there would be nothing for it to call.

The consequence is worth stating plainly rather than leaving to be discovered:
**production serves the risk scores that were seeded from `predictions.json`.**
The scheduled ingest and re-scoring happen on a developer machine and stay
there. See [orchestration.md](./orchestration.md).

---

## Connecting via SSM

```bash
# From AWS Console → Systems Manager → Session Manager → Start session
# Or via AWS CLI:
aws ssm start-session --target <instance-id>
```

No key pair or VPN required — IAM permissions govern access.

---

## Deploying a New Version (CI/CD)

Deployment is automated and split into two chained workflows so **no image is ever built on
the production instance** (`t3.micro`, ~916 MB RAM — a `vite build` running in place there
used to starve/OOM-kill the running containers, taking the site down for the duration of
every deploy; see [Why deploys used to cause an outage](#why-deploys-used-to-cause-an-outage)).

1. **`.github/workflows/build-images.yml`** — triggers on push to `main`. Builds
   `elevator-backend` (from `./backend`, also used by the `migrate` service) and
   `elevator-frontend` (from `./frontend`) and pushes both to GHCR
   (`ghcr.io/danielssj80/elevator-backend`, `.../elevator-frontend`), tagged `latest` and
   the commit SHA. Both packages are public, so the EC2 instance needs no registry
   credentials to pull them. A cleanup step retains `latest` plus the 10 most recent
   SHA-tagged versions per image.
2. **`.github/workflows/deploy.yml`** — triggers via `workflow_run` once `build-images.yml`
   completes, and only runs its deploy steps `if: ... conclusion == 'success'` (a failed
   build never deploys). It:
   1. Authenticates to AWS via OIDC (assumes the `github-actions-deploy` IAM role — no
      stored AWS or SSH credentials).
   2. Sends an SSM `AWS-RunShellScript` command to the instance that runs:
      `cd /opt/elevator && git fetch origin main && git reset --hard origin/main` and then
      recreates the stack with `docker compose pull && docker compose up -d` — **no
      `--build`**. The Compose file list always includes `docker-compose.prod.yml` and
      **additionally** includes `/opt/portfolio/docker-compose.portfolio.yml` when that
      file exists (see [Co-located sites](#co-located-sites-shared-nginx)). When the
      override is included, the merged nginx config is validated with `nginx -t` in a
      throwaway container first, falling back to an Elevator-only deploy if it is invalid;
      the `pull && up` is wrapped in `flock -w 600 /opt/deploy.lock`.
   3. Polls the command, streams its stdout/stderr into the Actions log, and fails the job
      if the remote command does not finish with status `Success`.
   4. Runs a smoke check against `https://elevator.dsaavedra.dev/health`.

Watch a run:

```bash
gh run watch
gh run view --log
```

### Required GitHub Actions variables

| Variable | Value |
|---|---|
| `AWS_REGION` | `eu-north-1` |
| `EC2_INSTANCE_ID` | the production instance ID (`i-...`) |
| `AWS_DEPLOY_ROLE_ARN` | ARN of the `github-actions-deploy` IAM role |

### Required AWS IAM setup (one-time)

- An IAM OIDC identity provider for `token.actions.githubusercontent.com`.
- An IAM role `github-actions-deploy` whose trust policy is scoped to `repo:danielssj80/Elevator-maintenance-flow-demo-project:ref:refs/heads/main`, with a permission policy allowing only `ssm:SendCommand` (scoped to the instance and the `AWS-RunShellScript` document) and `ssm:GetCommandInvocation`.

---

## Manual Deploy / Rollback Fallback

If CI is unavailable, or to roll back to a previous commit, deploy by hand over SSM:

```bash
# 1. Open SSM session
aws ssm start-session --target <instance-id>

# 2. Move the working copy to the desired commit
cd /opt/elevator
git fetch origin main
git reset --hard origin/main        # or: git reset --hard <previous-sha> to roll back

# 3. Pull the latest images and restart — NEVER add --build here (see
#    "Why deploys used to cause an outage" below). Include the portfolio override only
#    if it exists, validate the merged nginx config (falling back to Elevator-only on
#    failure), and serialize with the lock, mirroring the CI/CD command
#    (see "Co-located sites" below).
CF="-f docker-compose.prod.yml"
if [ -f /opt/portfolio/docker-compose.portfolio.yml ]; then
  CF="$CF -f /opt/portfolio/docker-compose.portfolio.yml"
  if ! docker compose $CF run --rm --no-deps --entrypoint nginx nginx -t; then
    echo "WARNING: merged nginx config invalid; deploying Elevator without the portfolio override" >&2
    CF="-f docker-compose.prod.yml"
  fi
fi
flock -w 600 /opt/deploy.lock sh -c "docker compose $CF pull && docker compose $CF up -d"

# To roll back to a specific previous image (rather than whatever is currently :latest
# in GHCR), pull it explicitly by SHA tag before `up -d`, e.g.:
#   docker pull ghcr.io/danielssj80/elevator-backend:<previous-sha>
#   docker tag ghcr.io/danielssj80/elevator-backend:<previous-sha> ghcr.io/danielssj80/elevator-backend:latest
```

---

## Co-located sites (shared nginx)

A second site — the personal portfolio at `https://dsaavedra.dev` — is served from the
**same nginx container** that fronts the Elevator stack (nginx owns ports 80/443 and the
`*.dsaavedra.dev` + apex certificate). The portfolio is deployed from a separate
repository (`dsaavedra-web`), checked out at `/opt/portfolio`, and attaches to nginx via
a Compose override (`/opt/portfolio/docker-compose.portfolio.yml`) that adds two
read-only mounts to the `nginx` service: the static root and a `conf.d` drop-in
(`portfolio.conf`).

Because the nginx container is shared, the two pipelines are coordinated so they cannot
break each other:

- **Conditional override** — the Elevator deploy includes the portfolio override only
  when `/opt/portfolio/docker-compose.portfolio.yml` exists, so it never recreates nginx
  without the portfolio mounts, and never fails if the portfolio is absent.
- **Merged-config validation + fallback** — when the override is included, the Elevator
  deploy validates the merged nginx config with `nginx -t` in a throwaway container and,
  if it is invalid, drops the override and deploys Elevator alone. This guarantees a
  broken co-located `portfolio.conf` (left on disk by a failed portfolio deploy) can
  never take Elevator down. The portfolio deploy validates the same way before applying.
- **Host-level lock** — both deploys wrap `docker compose ... up` in
  `flock -w 600 /opt/deploy.lock` (GitHub `concurrency` groups are per-repo and cannot
  coordinate across repositories); the bounded wait fails the deploy rather than hanging.

---

## Why deploys used to cause an outage

Before this change, `deploy.yml` ran `docker compose up --build -d` directly on the
production instance. Building the frontend image (`vite build`) is memory-hungry; on a
`t3.micro` (~916 MB RAM, no swap at the time), it starved the running containers and the
OOM killer took down `elevator.dsaavedra.dev` **and** the co-located `dsaavedra.dev` for
the duration of every deploy build, self-recovering once the build finished. Confirmed live
on the instance (`free -h` showed ~67 Mi free; `dmesg` showed OOM kills).

The fix has two parts:
- **Root fix (this change)**: images are built in GitHub Actions and pushed to GHCR; the
  instance only ever runs `docker compose pull && up -d` — no build, no OOM risk,
  regardless of available memory.
- **Standing safety margin**: a 2 GB swapfile was added to the instance
  (`/swapfile`, `vm.swappiness=10`) so any future memory-hungry process degrades instead of
  triggering an OOM kill. It is no longer load-bearing for deploys after this change.

---

## Checking Stack Health

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs --tail=50 backend
curl -s https://elevator.dsaavedra.dev/health
```

---

## TLS Certificate Renewal

Certbot runs from a **systemd timer**, and every file that configures it lives in
`deploy/tls/` in this repository. Nothing here is typed on the instance:

| Repository file | Installed to |
|---|---|
| `deploy/tls/certbot-renew.service` | `/etc/systemd/system/certbot-renew.service` |
| `deploy/tls/certbot-renew.timer` | `/etc/systemd/system/certbot-renew.timer` |
| `deploy/tls/reload-nginx-deploy-hook.sh` | `/etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh` |

The timer checks twice daily (03:00 and 15:00, with up to an hour of jitter) and
`Persistent=true` runs a trigger that was missed while the instance was off. The
service invokes certbot by **absolute path**. The nginx reload is a certbot deploy
hook, so it runs only when a certificate was actually renewed, it runs whoever
invoked certbot, and it passes `exec -T` because there is no TTY in a timer.

`deploy/tls/install-renewal.sh` installs all three, enables the timer, refuses to
proceed if the certbot binary the unit names is absent, and removes any legacy
crontab renewer after backing the crontab up. **`.github/workflows/deploy.yml`
runs it on every deploy**, after the smoke check — so host configuration is
restored from the repository continuously, and editing these files on the instance
accomplishes nothing but a delay until the next deploy.

Certificates are stored at `/etc/letsencrypt/live/dsaavedra.dev/` and mounted
read-only into the nginx container.

### Verifying it

```bash
systemctl list-timers --all certbot-renew.timer    # armed, and when next?
sudo journalctl -u certbot-renew -n 50             # did it run, and what did it return?
sudo systemctl start certbot-renew.service         # run it now, in the unit's own environment
sudo /usr/local/bin/certbot renew --dry-run --run-deploy-hooks
```

**`sudo` on the `journalctl` line is not optional.** The SSM shell user is not in
`adm`, `systemd-journal` or `wheel`, so without it journald prints `-- No entries --`
for a unit that ran perfectly — which reads exactly like "renewal has never run",
the conclusion this whole mechanism exists to make impossible to reach by accident.

In `list-timers`, a `LAST` and `PASSED` of `-` means the *timer* has not fired yet.
A run started by hand with `systemctl start` does not set them, so `-` there is not
evidence of anything either way; the journal is.

`--run-deploy-hooks` is not optional in that last command. **A plain `--dry-run`
does not execute deploy hooks**, so it proves the renewal and nothing whatsoever
about the reload.

### Expiry is watched from outside the host

`scripts/check-tls-expiry.sh <host> [min_days]` reads the certificate a host
actually **serves** and fails below 21 days — inside certbot's 30-day renewal
window, so a failure means the mechanism is broken rather than that renewal is
due. `.github/workflows/tls-expiry-check.yml` runs it daily against
`elevator.dsaavedra.dev` and `dsaavedra.dev`, and `deploy.yml` runs it on every
deploy. Run it by hand any time:

```bash
sh scripts/check-tls-expiry.sh elevator.dsaavedra.dev
sh scripts/check-tls-expiry.sh 127.0.0.1:8443 30   # host:port, for a local test server
```

It needs GNU `date` (`date -u -d`), which the instance and the CI runners have; on
macOS use `gdate` from coreutils.

It checks the served certificate rather than the file on disk because a file check
passes in the failure mode where renewal succeeds and the reload does not.

> **The check has a limitation worth knowing.** GitHub disables scheduled
> workflows after 60 days of repository inactivity, so this is not a monitor with
> a lifetime independent of the repository. `workflow_dispatch` and the deploy's
> own run of the script are the mitigations.

### Two traps this mechanism exists because of

**1. cron's `PATH` on Amazon Linux 2023 versus a pip-installed certbot.** On
2026-09-10 the wildcard certificate expired after 93 days without a single
renewal, taking down `elevator.dsaavedra.dev` and the co-located `dsaavedra.dev`
together. The renewal was a crontab line beginning with a bare `certbot`; `cronie`
runs jobs with `PATH=/usr/bin:/bin`, and `pip3 install certbot` had put the binary
in `/usr/local/bin`. It exited 127 every night for three months and reported it
nowhere: `--quiet` suppressed the output, AL2023 ships no MTA so cron's mail to
root was discarded, and AL2023 keeps no `/var/log/cron` because cronie logs to
journald. Reproduce the environment, not the command:

```bash
sudo env PATH=/usr/bin:/bin certbot --version   # what cron actually saw
```

systemd requires an absolute `ExecStart`, so this defect cannot be written into a
unit file — which is the substantive reason for the timer, not a preference.

**2. certbot is running on Python 3.9, and that deadline has passed.** certbot
4.2.0 warns on every run that Python 3.9 support is being dropped in its next
release, and boto3 — which the `dns-route53` plugin needs — ended Python 3.9
support in April 2026. An upgrade of either breaks renewal again. The expiry check
turns that into a 21-day warning rather than an outage; it does not prevent it.
Moving the certbot runtime is tracked as separate work.

The full incident write-up lives with the change that fixed it, under
`openspec/changes/harden-tls-renewal/reports/2026-09-13-incident-tls-expiry.md`
(after archiving, the same file under `openspec/changes/archive/`).

---

## Production Secrets

Generate `/etc/elevator/.env` with a single random password (the app builds `DATABASE_URL` from components — no duplication needed):

```bash
PASS=$(openssl rand -base64 32)
cat > /etc/elevator/.env << EOF
POSTGRES_USER=elevator
POSTGRES_PASSWORD=$PASS
POSTGRES_DB=elevator_db
POSTGRES_HOST=db
ALLOWED_ORIGINS=https://elevator.dsaavedra.dev
EOF
chmod 600 /etc/elevator/.env
```

To rotate credentials: update `POSTGRES_PASSWORD` in the file, then `docker compose -f docker-compose.prod.yml restart backend db`.
