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

Certbot runs automatically via cron at 03:00 daily:

```
0 3 * * * certbot renew --quiet && docker compose -f /opt/elevator/docker-compose.prod.yml exec nginx nginx -s reload
```

Manual dry-run check:

```bash
certbot renew --dry-run
```

Certificates are stored at `/etc/letsencrypt/live/dsaavedra.dev/` and mounted read-only into the nginx container.

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
