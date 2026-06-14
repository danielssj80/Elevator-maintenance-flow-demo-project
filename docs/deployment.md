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
   `cd /opt/elevator && git fetch origin main && git reset --hard origin/main && docker compose -f docker-compose.prod.yml up --build -d`
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
docker compose -f docker-compose.prod.yml up -d --build
```

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
