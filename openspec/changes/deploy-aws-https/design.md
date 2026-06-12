# Design: deploy-aws-https

## Overview

This change adds the production deployment layer. All code changes are minimal: a new Compose file, a new nginx config, and a two-line CORS refactor in the backend. The bulk of the work is one-time AWS infrastructure setup performed via SSM shell on the EC2 instance.

---

## 1. AWS Infrastructure

### EC2 Instance

| Setting | Value |
|---|---|
| Instance type | t3.micro |
| AMI | Amazon Linux 2023 (latest) |
| Region | us-east-1 |
| Key pair | None (SSM access only) |
| IAM instance profile | `elevator-ssm-profile` (AmazonSSMManagedInstanceCore) |
| Security group | Inbound: TCP 80, TCP 443 (source 0.0.0.0/0); no port 22 |
| EBS | 20 GB gp3 |

### Networking

- Allocate an Elastic IP and associate it with the instance
- Route 53: create A record `elevator.dsaavedra.dev` → Elastic IP (TTL 300)

### IAM

- **Instance profile** `elevator-ssm-profile`: attach `AmazonSSMManagedInstanceCore` managed policy — enables SSM Session Manager
- **IAM user** `certbot-route53`: programmatic access only; inline policy allows only `route53:ChangeResourceRecordSets` and `route53:ListHostedZones` on the `dsaavedra.dev` hosted zone ARN

---

## 2. docker-compose.prod.yml

New file at repo root. Differences from `docker-compose.yml`:

- `db`: named volume `elevator_postgres_data_prod`; **no** `ports` mapping (DB not reachable from outside)
- All services: `restart: always`
- `backend`: reads from `/etc/elevator/.env` (mounted as env file); no `TEST_DATABASE_URL` needed
- `frontend`: `ports` mapping removed (nginx proxies to container)
- New `nginx` service: official `nginx:alpine` image, mounts `./nginx/prod.conf` and Let's Encrypt cert/key from host filesystem

```yaml
services:
  db:
    image: postgres:16-alpine
    env_file: /etc/elevator/.env
    volumes:
      - elevator_postgres_data_prod:/var/lib/postgresql/data
    restart: always
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 5s
      timeout: 5s
      retries: 5

  migrate:
    build: ./backend
    command: alembic upgrade head
    env_file: /etc/elevator/.env
    depends_on:
      db:
        condition: service_healthy
    restart: on-failure

  backend:
    build: ./backend
    env_file: /etc/elevator/.env
    depends_on:
      db:
        condition: service_healthy
      migrate:
        condition: service_completed_successfully
    restart: always
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 10s
      timeout: 5s
      retries: 3

  frontend:
    build: ./frontend
    depends_on:
      backend:
        condition: service_healthy
    restart: always

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/prod.conf:/etc/nginx/conf.d/default.conf:ro
      - /etc/letsencrypt:/etc/letsencrypt:ro
    depends_on:
      - frontend
      - backend
    restart: always

volumes:
  elevator_postgres_data_prod:
```

---

## 3. nginx/prod.conf

Handles HTTP→HTTPS redirect and reverse-proxies to the backend and frontend containers:

```nginx
server {
    listen 80;
    server_name elevator.dsaavedra.dev;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name elevator.dsaavedra.dev;

    ssl_certificate     /etc/letsencrypt/live/dsaavedra.dev/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/dsaavedra.dev/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    location /api/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /health {
        proxy_pass http://backend:8000;
    }

    location / {
        proxy_pass http://frontend:80;
        proxy_set_header Host $host;
    }
}
```

---

## 4. CORS Refactor (backend/app/core/config.py + main.py)

**config.py** — add `allowed_origins` field:

```python
import os

class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://user:password@localhost:5432/elevator_db",
    )
    test_database_url: str = os.getenv(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://user:password@localhost:5432/elevator_test_db",
    )
    allowed_origins: list[str] = os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:5173,http://frontend:5173",
    ).split(",")
```

**main.py** — use `settings.allowed_origins`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

The production `.env` at `/etc/elevator/.env` includes:

```
ALLOWED_ORIGINS=https://elevator.dsaavedra.dev
```

---

## 5. /etc/elevator/.env (production secrets — NOT committed)

```
# PostgreSQL
POSTGRES_USER=elevator
POSTGRES_PASSWORD=<strong-random-password>
POSTGRES_DB=elevator_db
DATABASE_URL=postgresql+asyncpg://elevator:<password>@db:5432/elevator_db

# FastAPI
ALLOWED_ORIGINS=https://elevator.dsaavedra.dev
```

Permissions: `chmod 600 /etc/elevator/.env && chown root:root /etc/elevator/.env`

---

## 6. Let's Encrypt Certificate

Install certbot + DNS plugin on the EC2 host (not inside Docker):

```bash
pip3 install certbot certbot-dns-route53
```

Configure AWS credentials for `certbot-route53` IAM user in `/root/.aws/credentials`.

Obtain wildcard cert:

```bash
certbot certonly \
  --dns-route53 \
  -d "dsaavedra.dev" \
  -d "*.dsaavedra.dev" \
  --email danielssj@gmail.com \
  --agree-tos \
  --non-interactive
```

Certificate stored at `/etc/letsencrypt/live/dsaavedra.dev/` — mounted read-only into the nginx container.

Add cron for auto-renewal:

```
0 3 * * * certbot renew --quiet && docker compose -f /opt/elevator/docker-compose.prod.yml exec nginx nginx -s reload
```

---

## 7. Deployment Steps (one-time, via SSM shell)

1. Launch EC2 instance with SSM profile and SG (80+443)
2. Allocate Elastic IP; associate with instance; create Route 53 A record
3. Connect via SSM Session Manager
4. Install Docker + Docker Compose plugin on Amazon Linux 2023
5. Clone repo to `/opt/elevator/`
6. Create `/etc/elevator/.env` with production secrets
7. Configure certbot IAM credentials
8. Obtain Let's Encrypt cert
9. `docker compose -f /opt/elevator/docker-compose.prod.yml up -d --build`
10. Verify `/health`, HTTP redirect, HTTPS dashboard
11. Add certbot renewal cron

---

## 8. No Test Changes

The 22 existing unit tests and Playwright E2E tests are unaffected:
- Unit tests mock repositories; no network involved
- E2E tests run against `localhost` in the dev stack
- The CORS refactor is purely additive (default value matches current hardcoded list)
