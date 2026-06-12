## Why

The application runs locally but has no public URL — it cannot be shown to stakeholders or used for real demos. Deploying it to AWS with HTTPS makes it accessible at `https://elevator.dsaavedra.dev` as a persistent, shareable demo environment.

## What Changes

- New `docker-compose.prod.yml` — production Compose file with named DB volume, no exposed DB port, and `restart: always` on all services
- New `nginx/prod.conf` — nginx reverse proxy with HTTP→HTTPS 301 redirect, Let's Encrypt TLS, HSTS header
- Updated CORS config in `backend/app/core/config.py` — `ALLOWED_ORIGINS` driven by env var (no wildcard in production)
- AWS infrastructure: EC2 t3.micro (Amazon Linux 2023), Elastic IP, Route 53 A record `elevator.dsaavedra.dev`, SSM instance profile, security group allowing only ports 80 and 443
- Let's Encrypt wildcard cert `*.dsaavedra.dev` obtained via DNS-01 challenge with Route 53; auto-renewed by cron
- Production secrets at `/etc/elevator/.env` on EC2 with `chmod 600` — never committed to repo

## Capabilities

### New Capabilities

- `production-deployment`: Docker Compose production configuration, nginx TLS proxy, CORS env-var config, EC2 infrastructure, Let's Encrypt certificate management

### Modified Capabilities

- `database-infrastructure`: Production adds a named Docker volume for PostgreSQL data persistence across `docker compose down` cycles; no DB port exposed in production

## Impact

- **New files**: `docker-compose.prod.yml`, `nginx/prod.conf`, `nginx/` directory
- **Modified**: `backend/app/core/config.py` (CORS env var), `backend/app/main.py` (pass origins from config)
- **No frontend changes**: relative `/api/*` paths work transparently behind nginx
- **No schema/API changes**: same endpoints, same data model
- **No test changes**: existing 22 unit tests and Playwright E2E tests unaffected
- **Dependencies**: nginx (Docker image), certbot + certbot-dns-route53 (pip), AWS CLI v2
