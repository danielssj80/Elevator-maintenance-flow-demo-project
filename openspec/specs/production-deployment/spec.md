# Spec: production-deployment

## Purpose

Deploy the Elevator Maintenance application to AWS as a publicly accessible HTTPS service at `https://elevator.dsaavedra.dev`, on a single EC2 instance reached only through SSM, with a Let's Encrypt certificate that renews itself and is watched from outside the host.

## Requirements

### Requirement: HTTP is redirected to HTTPS
The system SHALL serve no plaintext content: every HTTP request SHALL be answered with a permanent redirect to the same path over HTTPS.

#### Scenario: A plaintext request is redirected
- **WHEN** a client sends `GET http://elevator.dsaavedra.dev/` while the stack is running on EC2
- **THEN** the server responds with 301 and `Location: https://elevator.dsaavedra.dev/`

### Requirement: The dashboard loads over HTTPS with a trusted certificate
The system SHALL serve the dashboard over HTTPS with a certificate that a browser accepts without warnings, and SHALL load every subresource over HTTPS.

#### Scenario: The dashboard renders over HTTPS
- **WHEN** a browser opens `https://elevator.dsaavedra.dev` while the stack is running on EC2
- **THEN** the Elevator Maintenance dashboard renders with 100 elevator rows, sorted by risk score descending
- **AND** the browser shows a valid TLS certificate issued by Let's Encrypt
- **AND** no mixed-content warnings appear

### Requirement: The API is reachable over HTTPS
The system SHALL expose the application API and its health endpoint over HTTPS through the same host.

#### Scenario: The elevator list is served over HTTPS
- **WHEN** a client sends `GET https://elevator.dsaavedra.dev/api/elevators`
- **THEN** the response is 200 with a JSON array of 100 elevators

#### Scenario: The health endpoint is served over HTTPS
- **WHEN** a client sends `GET https://elevator.dsaavedra.dev/health`
- **THEN** the response is 200 with `{"status": "ok"}`

### Requirement: A post-visit report persists in production
The system SHALL persist a post-visit report submitted over HTTPS in the production database.

#### Scenario: A submitted report reaches the database
- **WHEN** a technician submits a POST to `https://elevator.dsaavedra.dev/api/elevators/ELV-001/report` with a valid body
- **THEN** the response is 201
- **AND** the row is present in the `visit_reports` table of the production PostgreSQL instance

### Requirement: The stack restarts automatically after a reboot
The system SHALL return to service after an instance reboot with no manual intervention.

#### Scenario: The instance is rebooted
- **WHEN** the EC2 instance completes its boot sequence after a reboot
- **THEN** the Docker stack is running without manual intervention within 60 seconds
- **AND** `https://elevator.dsaavedra.dev/health` returns 200

### Requirement: Shell access is via SSM, with no SSH
Shell access to the instance SHALL be granted through AWS SSM Session Manager and IAM permissions alone. Port 22 SHALL NOT be open.

#### Scenario: An authorised engineer opens a session
- **WHEN** an engineer with the `AmazonSSMManagedInstanceCore` IAM permission opens an SSM Session Manager session to the instance
- **THEN** they obtain an interactive shell
- **AND** port 22 is not open in the security group

### Requirement: The production certificate renews itself without human intervention
The system SHALL renew the production TLS certificate before expiry with no operator action, and the mechanism that does so SHALL satisfy all of the following:

- Its definition SHALL live in version control and SHALL be installed onto the host by the deployment pipeline, so that it is reproducible on a rebuilt instance and visible to the test suite.
- It SHALL invoke the certbot binary by **absolute path**. An invocation that relies on the scheduler's `PATH` is non-conforming, whether or not it happens to work in an interactive shell.
- It SHALL attempt renewal at least twice per day, and SHALL run a trigger that was missed while the instance was powered off.
- Reloading the web server SHALL be performed by certbot on successful renewal, not by a shell operator chained to the renewal command, and SHALL require no controlling terminal.
- Exactly one renewal mechanism SHALL be active on the host.

Verification of this requirement SHALL be performed under the environment the scheduler provides, not in an interactive shell. A dry run typed by an operator is **not** evidence for it: that is what was accepted for this requirement's predecessor, and the certificate then went 93 days without a renewal and expired.

#### Scenario: Renewal succeeds under the scheduler's environment
- **WHEN** renewal is invoked with the environment the scheduler provides, with no inherited shell configuration and a `PATH` of `/usr/bin:/bin`
- **THEN** certbot executes and reports the renewal check as successful
- **AND** an invocation naming the binary without a path fails, and is therefore not what the installed unit contains

#### Scenario: A renewed certificate reaches the running web server
- **WHEN** a renewal completes successfully
- **THEN** certbot runs the deploy hook that reloads nginx, with no terminal attached
- **AND** the certificate presented to clients afterwards is the renewed one

#### Scenario: A trigger missed while the instance was off is caught up
- **WHEN** the scheduled time passes while the instance is powered off
- **THEN** the renewal check runs after the instance next boots, rather than waiting for the following scheduled time

#### Scenario: Only one mechanism renews the certificate
- **WHEN** the renewal configuration has been installed
- **THEN** no crontab entry invoking certbot remains on the host
- **AND** the previous crontab content has been preserved as a backup

#### Scenario: A hand edit on the host does not survive
- **WHEN** the installed unit or hook is edited directly on the instance
- **THEN** the next deployment restores it from version control

#### Scenario: A reload that fails does not pass silently
- **WHEN** a renewal succeeds but the web server cannot be reloaded
- **THEN** the failure is reported as an error by the renewal run and recorded in the certbot log
- **AND** the externally scheduled expiry check reports the stale served certificate while there is still time to act on it

### Requirement: Certificate expiry is detected from outside the host before it happens
The system SHALL check, from outside the production instance and at least once per day, the certificate that each production hostname actually **serves**, and SHALL fail when fewer than 21 days remain before its expiry.

The threshold SHALL sit inside the renewal window — renewal begins at 30 days remaining — so that a failure means the renewal mechanism is broken rather than that renewal is merely due. The check SHALL validate the served chain without trust overrides, SHALL fail rather than pass when the host cannot be reached, and SHALL be runnable both on demand and by the deployment pipeline.

The subject of the check is the served certificate, not the file on disk: a file check cannot distinguish a healthy host from one that renewed successfully and is still presenting the expired certificate it holds in memory.

#### Scenario: A healthy certificate passes on every hostname
- **WHEN** the check runs against `elevator.dsaavedra.dev` and `dsaavedra.dev`
- **THEN** each host's served certificate validates and has at least 21 days remaining
- **AND** the check reports the expiry date it read for each host

#### Scenario: A stale served certificate fails even though the file is current
- **WHEN** the certificate on disk has been renewed but the server still presents the previous one
- **THEN** the check fails for that hostname

#### Scenario: An unreachable host fails the check
- **WHEN** the TLS connection cannot be established
- **THEN** the check fails, reporting that it could not read a certificate
- **AND** it does not report success for want of an expiry date to compare

#### Scenario: An untrusted chain fails regardless of the dates
- **WHEN** the served chain does not validate against the public trust store
- **THEN** the check fails even if the certificate's own dates are still in range

#### Scenario: A deployment reports certificate health
- **WHEN** a deployment completes its health check
- **THEN** it runs the same expiry check and reports the result in the run log

### Requirement: The pre-visit briefing works in production via Bedrock
The system SHALL serve the pre-visit briefing from Amazon Bedrock in production, and the IAM grant that allows it SHALL follow least privilege:

- it is a **customer-managed** policy (not inline), so it is independently versioned and auditable;
- the only action is `bedrock:InvokeModel` (no `bedrock:*`, no `Resource: "*"`);
- the foundation-model ARNs are pinned to the exact four regions the EU inference profile routes to (`eu-central-1`, `eu-north-1`, `eu-west-1`, `eu-west-3`) — no region wildcard;
- the backend authenticates via the instance role through IMDSv2 (tokens required) — no AWS credentials in code or `.env`.

#### Scenario: A briefing is generated in production
- **WHEN** a client sends `GET https://elevator.dsaavedra.dev/api/elevators/{id}/briefing` for an uncached in-scope unit, with the instance role (`elevator-ssm-role`) carrying the customer-managed policy `ElevatorBedrockInvokeNova` and `/etc/elevator/.env` containing `BEDROCK_REGION=eu-north-1` and `BEDROCK_MODEL_ID=eu.amazon.nova-lite-v1:0`
- **THEN** the response is 200 with `source: "bedrock"` and a non-empty `text`

### Requirement: CORS is enforced in production
The system SHALL restrict cross-origin access in production to the configured origin list, and SHALL NOT use a wildcard origin.

#### Scenario: An unlisted origin is refused
- **WHEN** a browser makes a cross-origin request from an unlisted origin, with the backend running with `ALLOWED_ORIGINS=https://elevator.dsaavedra.dev`
- **THEN** the response does not include `Access-Control-Allow-Origin` for that origin
- **AND** no wildcard `*` CORS origin is used in production

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
- Renewal configuration is installed from the repository by the deploy, never edited on the instance

---

## Files

| File | Purpose |
|---|---|
| `docker-compose.prod.yml` | Production Docker Compose: named DB volume, no exposed DB port, `restart: always` |
| `nginx/prod.conf` | nginx: HTTP→HTTPS redirect, HTTPS proxy to backend and frontend, TLS, HSTS |
| `backend/app/core/config.py` | `ALLOWED_ORIGINS: list[str]` from env var |
| `backend/app/main.py` | Pass `settings.allowed_origins` to `CORSMiddleware` |
| `deploy/tls/certbot-renew.service` | Renewal unit: certbot by absolute path |
| `deploy/tls/certbot-renew.timer` | Twice daily, jittered, `Persistent=true` |
| `deploy/tls/reload-nginx-deploy-hook.sh` | nginx reload, run by certbot after a successful renewal |
| `deploy/tls/install-renewal.sh` | Installs the above; run by every deploy; removes the legacy crontab renewer |
| `scripts/check-tls-expiry.sh` | Fails when the served certificate has under 21 days left |
| `.github/workflows/tls-expiry-check.yml` | Runs that check daily, off the host |

---

## Out of Scope

- RDS or managed database
- CloudFront CDN
- High availability or auto-scaling
- Alerting beyond a failing GitHub Actions run
- Staging environment
