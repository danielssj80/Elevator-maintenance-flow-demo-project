# Spec: production-deployment

Deploy the Elevator Maintenance application to AWS as a publicly accessible HTTPS service at `https://elevator.dsaavedra.dev`.

---

## Scenarios

### S1 — HTTP redirects to HTTPS

**Given** the stack is running on EC2  
**When** a client sends `GET http://elevator.dsaavedra.dev/`  
**Then** the server responds with 301 and `Location: https://elevator.dsaavedra.dev/`

### S2 — Dashboard loads over HTTPS

**Given** the stack is running on EC2  
**When** a browser opens `https://elevator.dsaavedra.dev`  
**Then** the Elevator Maintenance dashboard renders with 100 elevator rows, sorted by risk score descending  
**And** the browser shows a valid TLS certificate issued by Let's Encrypt  
**And** no mixed-content warnings appear

### S3 — API accessible over HTTPS

**Given** the stack is running on EC2  
**When** a client sends `GET https://elevator.dsaavedra.dev/api/elevators`  
**Then** the response is 200 with a JSON array of 100 elevators  
**When** a client sends `GET https://elevator.dsaavedra.dev/health`  
**Then** the response is 200 with `{"status": "ok"}`

### S4 — Post-visit report persists in production

**Given** the stack is running on EC2  
**When** a technician submits a POST to `https://elevator.dsaavedra.dev/api/elevators/ELV-001/report` with a valid body  
**Then** the response is 201  
**And** the row is present in the `visit_reports` table of the production PostgreSQL instance

### S5 — Stack restarts automatically on reboot

**Given** the EC2 instance is rebooted  
**When** the instance completes its boot sequence  
**Then** the Docker stack is running without manual intervention within 60 seconds  
**And** `https://elevator.dsaavedra.dev/health` returns 200

### S6 — Shell access via SSM (no SSH)

**Given** an engineer has the `AmazonSSMManagedInstanceCore` IAM permission  
**When** they open an SSM Session Manager session to the EC2 instance  
**Then** they obtain an interactive shell  
**And** port 22 is not open in the security group

### S7 — Certificate auto-renewal

**Given** the Let's Encrypt certificate is within 30 days of expiry  
**When** the certbot renewal cron job runs  
**Then** `certbot renew` completes successfully and nginx reloads with the renewed certificate  
**And** `certbot renew --dry-run` succeeds at any time

### S9 — Pre-visit briefing works in production (Bedrock)

**Given** the EC2 instance role (`elevator-ssm-role`) has the customer-managed policy `ElevatorBedrockInvokeNova` attached, granting `bedrock:InvokeModel` on the EU Nova Lite inference-profile ARN and its four routed foundation-model ARNs  
**And** `/etc/elevator/.env` contains `BEDROCK_REGION=eu-north-1` and `BEDROCK_MODEL_ID=eu.amazon.nova-lite-v1:0`  
**When** a client sends `GET https://elevator.dsaavedra.dev/api/elevators/{id}/briefing` for an uncached in-scope unit  
**Then** the response is 200 with `source: "bedrock"` and a non-empty `text`

**And** the briefing IAM grant follows least privilege:
- it is a **customer-managed** policy (not inline), so it is independently versioned and auditable;
- the only action is `bedrock:InvokeModel` (no `bedrock:*`, no `Resource: "*"`);
- the foundation-model ARNs are pinned to the exact four regions the EU inference profile routes to (`eu-central-1`, `eu-north-1`, `eu-west-1`, `eu-west-3`) — no region wildcard;
- the backend authenticates via the instance role through IMDSv2 (tokens required) — no AWS credentials in code or `.env`.

### S8 — CORS enforced in production

**Given** the backend is running with `ALLOWED_ORIGINS=https://elevator.dsaavedra.dev`  
**When** a browser makes a cross-origin request from an unlisted origin  
**Then** the response does not include `Access-Control-Allow-Origin` for that origin  
**And** no wildcard `*` CORS origin is used in production

---

## Constraints

- Instance type: `t3.micro` (AWS Free Tier eligible)
- OS: Amazon Linux 2023
- No SSH: security group allows inbound 80 (HTTP) and 443 (HTTPS) only
- Access method: AWS SSM Session Manager (IAM-based, no key pair required)
- TLS: Let's Encrypt via DNS-01 challenge (certbot-dns-route53), wildcard cert `*.dsaavedra.dev`
- TLS minimum version: TLS 1.2; HSTS header included in nginx response
- Secrets: production `.env` at `/etc/elevator/.env`, `chmod 600`, owned by root — never committed; must include `BEDROCK_REGION` and `BEDROCK_MODEL_ID`
- IAM certbot user (`certbot-route53`) scoped to single Route 53 hosted zone (least privilege)
- Bedrock access granted via customer-managed policy `ElevatorBedrockInvokeNova` attached to `elevator-ssm-role` — `bedrock:InvokeModel` only, scoped to the EU Nova Lite inference-profile ARN plus its four routed foundation-model ARNs (`eu-central-1`, `eu-north-1`, `eu-west-1`, `eu-west-3`); no inline policy, no region wildcard, no credentials in code (resolved via IMDSv2 instance role)
- PostgreSQL data on named Docker volume — survives `docker compose down`
- Production Compose file: `docker-compose.prod.yml` (separate from dev `docker-compose.yml`)

---

## Files

| File | Purpose |
|---|---|
| `docker-compose.prod.yml` | Production Docker Compose: named DB volume, no exposed DB port, `restart: always` |
| `nginx/prod.conf` | nginx: HTTP→HTTPS redirect, HTTPS proxy to backend and frontend, TLS, HSTS |
| `backend/app/core/config.py` | `ALLOWED_ORIGINS: list[str]` from env var |
| `backend/app/main.py` | Pass `settings.allowed_origins` to `CORSMiddleware` |

---

## Out of Scope

- RDS or managed database
- CloudFront CDN
- High availability or auto-scaling
- Monitoring and alerting
- Staging environment
