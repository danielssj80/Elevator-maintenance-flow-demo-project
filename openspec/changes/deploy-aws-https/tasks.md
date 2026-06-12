# Tasks: deploy-aws-https

## 0. Setup: Create Feature Branch (MANDATORY)

- [x] 0.1 Create branch `feature/deploy-aws-https` from `main`
- [x] 0.2 Verify current branch: `git -C /home/daniel/Claude-Code/Elevator-maintenance-flow-demo-project branch --show-current`

---

## 1. Backend: CORS Config Refactor

- [x] 1.1 Update `backend/app/core/config.py`: add `allowed_origins: list[str]` field reading from env var `ALLOWED_ORIGINS` (comma-separated), defaulting to `"http://localhost:5173,http://frontend:5173"`
- [x] 1.2 Update `backend/app/main.py`: replace hardcoded origin list with `settings.allowed_origins`
- [x] 1.3 Verify dev stack still works: `docker-compose up -d` and `curl -s http://localhost:8000/health`

---

## 2. Production Docker Compose

- [x] 2.1 Create `docker-compose.prod.yml` at repo root following the design (named volume `elevator_postgres_data_prod`, no DB port exposed, `restart: always` on all services, nginx service, env_file from `/etc/elevator/.env`)
- [x] 2.2 Verify file passes Compose validation: `docker-compose -f docker-compose.prod.yml config --quiet`

---

## 3. nginx Production Config

- [x] 3.1 Create `nginx/` directory at repo root
- [x] 3.2 Create `nginx/prod.conf` following the design (HTTP→HTTPS 301, TLS 1.2+, HSTS, proxy to backend and frontend containers)

---

## 4. Review and Update Existing Tests (MANDATORY)

- [x] 4.1 Review `backend/tests/` for any test that asserts on CORS origins (search for `localhost:5173` or `CORS`)
- [x] 4.2 Update any tests that hardcode the allowed origins list — they should now test the default from settings

---

## 5. Unit Tests and DB State Verification (MANDATORY)

- [x] 5.1 Capture pre-test DB baseline (table row counts)
- [x] 5.2 Run targeted tests for modified modules: `backend/venv/bin/python -m pytest tests/ -k "config or cors or main" -v`
- [x] 5.3 Run full unit test suite: `backend/venv/bin/python -m pytest tests/unit/ -v --cov=app --cov-report=term-missing`
- [x] 5.4 Verify post-test DB state matches baseline
- [x] 5.5 Create report `openspec/changes/deploy-aws-https/reports/YYYY-MM-DD-step-5-unit-tests.md`
- [x] 5.6 Mark complete only after report exists and all tests pass

---

## 6. Manual Endpoint Testing (MANDATORY — AGENT MUST EXECUTE)

- [x] 6.1 Ensure dev stack is running: `docker-compose up -d`
- [x] 6.2 Verify health endpoint: `curl -s http://localhost:8000/health`
- [x] 6.3 Verify CORS header present for allowed origin: `curl -s -H "Origin: http://localhost:5173" -I http://localhost:8000/api/elevators | grep -i access-control`
- [x] 6.4 Verify CORS header absent for unlisted origin: `curl -s -H "Origin: http://evil.example.com" -I http://localhost:8000/api/elevators | grep -i access-control` (should return nothing)
- [x] 6.5 Verify list endpoint still returns 100 elevators: `curl -s http://localhost:8000/api/elevators | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d))"`
- [x] 6.6 Create report `openspec/changes/deploy-aws-https/reports/YYYY-MM-DD-step-6-endpoint-testing.md`

---

## 7. E2E Testing — Not Applicable

No frontend changes in this task. The UI is unchanged — existing Playwright E2E tests remain valid.
Confirm dev stack renders correctly as a sanity check if desired.

---

## 8. AWS Infrastructure Setup (One-Time, Manual via Console + SSM)

> These steps are executed once by the operator in the AWS Console and SSM shell. They cannot be automated by the agent.

- [ ] 8.1 Launch EC2 instance: t3.micro, Amazon Linux 2023, IAM instance profile `elevator-ssm-profile` (AmazonSSMManagedInstanceCore), SG inbound TCP 80 + TCP 443 only, 20 GB gp3, no key pair
- [ ] 8.2 Allocate Elastic IP and associate with instance
- [ ] 8.3 Create IAM user `certbot-route53` with inline policy: `route53:ChangeResourceRecordSets` + `route53:ListHostedZones` on the `dsaavedra.dev` hosted zone ARN only
- [ ] 8.4 In Route 53: create A record `elevator.dsaavedra.dev` → Elastic IP (TTL 300)
- [ ] 8.5 Verify SSM Session Manager connection: open session from AWS Console → Systems Manager → Session Manager

---

## 9. Production Deployment (Via SSM Shell)

> Execute these commands in the SSM shell session on the EC2 instance.

- [ ] 9.1 Install Docker and Docker Compose plugin on Amazon Linux 2023:
  ```bash
  dnf update -y
  dnf install -y docker
  systemctl enable --now docker
  mkdir -p /usr/local/lib/docker/cli-plugins
  curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 -o /usr/local/lib/docker/cli-plugins/docker-compose
  chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
  ```
- [ ] 9.2 Clone repo to `/opt/elevator/`:
  ```bash
  dnf install -y git
  git clone https://github.com/<org>/elevator-maintenance-flow-demo-project.git /opt/elevator
  ```
- [ ] 9.3 Create `/etc/elevator/.env` with production secrets (see design §5), then `chmod 600 /etc/elevator/.env && chown root:root /etc/elevator/.env`
- [ ] 9.4 Install certbot with DNS-Route53 plugin:
  ```bash
  dnf install -y python3-pip
  pip3 install certbot certbot-dns-route53
  ```
- [ ] 9.5 Configure certbot IAM credentials in `/root/.aws/credentials` (access key for `certbot-route53` user)
- [ ] 9.6 Obtain wildcard Let's Encrypt certificate:
  ```bash
  certbot certonly --dns-route53 -d "dsaavedra.dev" -d "*.dsaavedra.dev" \
    --email danielssj@gmail.com --agree-tos --non-interactive
  ```
- [ ] 9.7 Start production stack:
  ```bash
  cd /opt/elevator && docker compose -f docker-compose.prod.yml up -d --build
  ```
- [ ] 9.8 Add certbot renewal cron (as root):
  ```bash
  echo "0 3 * * * certbot renew --quiet && docker compose -f /opt/elevator/docker-compose.prod.yml exec nginx nginx -s reload" | crontab -
  ```

---

## 10. Production Verification (MANDATORY — AGENT MUST EXECUTE via curl)

- [ ] 10.1 Verify HTTP redirects to HTTPS: `curl -s -o /dev/null -w "%{http_code} %{redirect_url}" http://elevator.dsaavedra.dev/` → expect `301 https://elevator.dsaavedra.dev/`
- [ ] 10.2 Verify health endpoint over HTTPS: `curl -s https://elevator.dsaavedra.dev/health` → expect `{"status":"ok"}`
- [ ] 10.3 Verify TLS certificate issuer: `curl -v https://elevator.dsaavedra.dev/health 2>&1 | grep -i "issuer"` → expect Let's Encrypt
- [ ] 10.4 Verify API returns 100 elevators: `curl -s https://elevator.dsaavedra.dev/api/elevators | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d))"` → expect `100`
- [ ] 10.5 Submit a test report via HTTPS:
  ```bash
  curl -s -X POST https://elevator.dsaavedra.dev/api/elevators/ELV-001/report \
    -H "Content-Type: application/json" \
    -d '{"technician_name":"Deploy Test","visit_date":"2026-06-12","failure_found":false}' \
    | python3 -m json.tool
  ```
  Expect 201; verify row exists in DB via SSM psql; then delete test row.
- [ ] 10.6 Verify certbot renewal dry-run: `certbot renew --dry-run` → expect success
- [ ] 10.7 Create report `openspec/changes/deploy-aws-https/reports/YYYY-MM-DD-step-10-production-verification.md`

---

## 11. Update Technical Documentation (MANDATORY)

- [x] 11.1 Update `docs/api-spec.yml`: add production server `https://elevator.dsaavedra.dev` to the `servers` list
- [x] 11.2 No data model changes — `docs/data-model.md` does not need updating
- [x] 11.3 No new backend patterns — `docs/backend-standards.md` does not need updating
- [x] 11.4 Add production deployment section to project README or create `docs/deployment.md` with: EC2 setup, SSM access instructions, cert renewal, and how to deploy a new version
