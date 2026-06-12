# Deployment Guide

The application is deployed to AWS EC2 at **https://elevator.dsaavedra.dev**.

---

## Infrastructure

| Component | Detail |
|---|---|
| Instance | EC2 t3.micro, Amazon Linux 2023, us-east-1 |
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

## Deploying a New Version

```bash
# 1. Open SSM session
aws ssm start-session --target <instance-id>

# 2. Pull latest code
cd /opt/elevator
git pull origin main

# 3. Rebuild and restart (zero-downtime: containers restart one at a time)
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
