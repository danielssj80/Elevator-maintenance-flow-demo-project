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

## Connecting via SSM

```bash
# From AWS Console → Systems Manager → Session Manager → Start session
# Or via AWS CLI:
aws ssm start-session --target <instance-id>
```

No key pair or VPN required — IAM permissions govern access.

---

## Deploying a New Version (CI/CD)

Deployment is automated. **Pushing to `main` deploys to production** — no manual step required.

The GitHub Actions workflow `.github/workflows/deploy.yml`:

1. Authenticates to AWS via OIDC (assumes the `github-actions-deploy` IAM role — no stored AWS or SSH credentials).
2. Sends an SSM `AWS-RunShellScript` command to the instance that runs:
   `cd /opt/elevator && git fetch origin main && git reset --hard origin/main` and then recreates the stack with `docker compose up --build -d`. The Compose file list always includes `docker-compose.prod.yml` and **additionally** includes `/opt/portfolio/docker-compose.portfolio.yml` when that file exists (see [Co-located sites](#co-located-sites-shared-nginx)). When the override is included, the merged nginx config is validated with `nginx -t` in a throwaway container first, falling back to an Elevator-only deploy if it is invalid; the `up` is wrapped in `flock -w 600 /opt/deploy.lock`.
3. Polls the command, streams its stdout/stderr into the Actions log, and fails the job if the remote command does not finish with status `Success`.
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

# 3. Rebuild and restart
#    Include the portfolio override only if it exists, validate the merged nginx
#    config (falling back to Elevator-only on failure), and serialize with the lock,
#    mirroring the CI/CD command (see "Co-located sites" below).
CF="-f docker-compose.prod.yml"
if [ -f /opt/portfolio/docker-compose.portfolio.yml ]; then
  CF="$CF -f /opt/portfolio/docker-compose.portfolio.yml"
  if ! docker compose $CF run --rm --no-deps --entrypoint nginx nginx -t; then
    echo "WARNING: merged nginx config invalid; deploying Elevator without the portfolio override" >&2
    CF="-f docker-compose.prod.yml"
  fi
fi
flock -w 600 /opt/deploy.lock docker compose $CF up -d --build
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
