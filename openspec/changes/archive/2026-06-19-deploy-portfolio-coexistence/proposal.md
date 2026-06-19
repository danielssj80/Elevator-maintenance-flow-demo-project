# Proposal: deploy-portfolio-coexistence

## Why

A second site — the personal portfolio at `https://dsaavedra.dev` — is being added to the same EC2 instance, served by the **same nginx container** that already fronts the Elevator stack (it owns ports 80/443 and the `*.dsaavedra.dev` + apex TLS certificate). The portfolio lives in a separate repository (`dsaavedra-web`, checked out at `/opt/portfolio`) and attaches to nginx through a Compose override that adds two read-only mounts.

Because the nginx container is shared, the Elevator deploy command — which runs `docker compose ... up -d` — would, as written today, recreate nginx **without** the portfolio's override mounts, taking the apex site down on every Elevator deploy. The Elevator deploy must become aware of the co-located site so the two pipelines cannot break each other.

## What Changes

- The SSM deploy command in `.github/workflows/deploy.yml` includes the portfolio Compose override **conditionally** — only when `/opt/portfolio/docker-compose.portfolio.yml` exists — so nginx is always recreated with the portfolio mounts intact, and the Elevator deploy still works unchanged when the portfolio is absent.
- The `docker compose ... up` invocation is wrapped in `flock /opt/deploy.lock` so the Elevator and portfolio pipelines serialize on the host and never mutate Docker state concurrently (GitHub `concurrency` groups are per-repo and cannot coordinate across repositories).
- No application code, no backend/frontend, no DB schema changes.

## Capabilities

### Modified Capabilities

- `deploy-pipeline`: the remote deploy command now composes the Elevator stack file with the portfolio override when present, and serializes the `up` with a host-level lock, so co-located sites on the shared nginx are preserved and concurrent deploys are safe.

## Impact

- **Modified files**: `.github/workflows/deploy.yml` (deploy command only — auth, polling, smoke check unchanged)
- **Docs**: `docs/deployment.md` (document the shared-nginx coexistence model and the new deploy command)
- **Application code**: none
- **AWS / IAM**: none in this change. Extending the `github-actions-deploy` trust policy to the `dsaavedra-web` repo, the read-only deploy key, the Route 53 apex records, and the portfolio override/conf files are all owned by the `dsaavedra-web` rollout, not by Elevator.

## Out of Scope

- The portfolio repository, its content, its `nginx/portfolio.conf`, and its `docker-compose.portfolio.yml` (live in `dsaavedra-web`).
- IAM trust-policy extension and Route 53 records for the apex (part of the `dsaavedra-web` rollout).
- Any change to the Elevator services, ports, or TLS certificate.
