# Design: deploy-portfolio-coexistence

## Context

The production EC2 instance now hosts two independent sites behind one nginx container:

- **Elevator** (`elevator.dsaavedra.dev`) — full stack in `/opt/elevator`, deployed from this repo.
- **Portfolio** (`dsaavedra.dev`) — static site in `/opt/portfolio`, deployed from `dsaavedra-web`.

nginx belongs to the Elevator Compose project and owns ports 80/443 and the shared certificate. The portfolio attaches via a Compose override (`/opt/portfolio/docker-compose.portfolio.yml`) that adds two read-only mounts to the `nginx` service: the static root and a `conf.d` drop-in (`portfolio.conf`). Compose merges these onto nginx's existing mounts.

This is infrastructure-only: no backend, frontend, database, or API surface is touched. The three-layer backend architecture and the frontend service-layer pattern do not apply.

## Decisions

### 1. Conditional override inclusion

The Elevator deploy builds its Compose file list dynamically and appends the portfolio override **only if it exists**:

```bash
COMPOSE="-f docker-compose.prod.yml"
[ -f /opt/portfolio/docker-compose.portfolio.yml ] && \
  COMPOSE="$COMPOSE -f /opt/portfolio/docker-compose.portfolio.yml"
flock /opt/deploy.lock docker compose $COMPOSE up --build -d
```

- **When the portfolio is present**: nginx is recreated *with* the portfolio mounts, so the apex site is never dropped by an Elevator deploy.
- **When the portfolio is absent**: the command degrades to exactly today's behaviour (`-f docker-compose.prod.yml` only), so Elevator never depends on the other repo and cannot be broken by its absence.

Rejected alternative — moving the override into the Elevator repo: would couple Elevator to portfolio content and defeat the separate-repo decision. A drop-in/override owned by `dsaavedra-web` keeps `nginx/prod.conf` untouched here.

### 2. Host-level serialization with `flock`

Both pipelines wrap the `up` in `flock /opt/deploy.lock`. GitHub Actions `concurrency` groups are scoped per repository, so they cannot prevent an Elevator deploy and a portfolio deploy from running their `docker compose up` simultaneously against the shared Docker state. A host-level advisory lock guarantees mutual exclusion regardless of which repo triggers.

### 3. Validate the merged config on the Elevator side, with fallback

The Elevator deploy validates the **merged** nginx config before recreating the shared container, and falls back to deploying Elevator alone if it fails:

```bash
if [ -f /opt/portfolio/docker-compose.portfolio.yml ]; then
  CF="$CF -f /opt/portfolio/docker-compose.portfolio.yml"
  if ! docker compose $CF run --rm --no-deps --entrypoint nginx nginx -t; then
    echo "WARNING: merged nginx config invalid; deploying Elevator without the portfolio override" >&2
    CF="-f docker-compose.prod.yml"
  fi
fi
flock -w 600 /opt/deploy.lock docker compose $CF up --build -d
```

**Why this is required** (corrects an earlier assumption that the portfolio pipeline's own gate was sufficient): both pipelines run `git reset --hard` *before* validating, so a broken `portfolio.conf` on `main` lands on disk at `/opt/portfolio/nginx/portfolio.conf` even though the portfolio pipeline aborts before applying it. The mount is a bind mount, so the **next Elevator deploy** would recreate nginx from that broken on-disk file and take **both** sites down. Validating the merged config here and dropping the override on failure guarantees the promise that the co-located site can never take Elevator down. The `nginx -t` runs in a throwaway container (`run --rm --no-deps`) so it never touches the running nginx, and the negated test (`if ! ...`) is exempt from `set -e`.

## Risks

- **Stale lock**: if a deploy is killed mid-`flock`, the lock is released when the process dies (advisory `flock` releases on fd close), so no manual cleanup is expected.
- **`/opt/deploy.lock` permissions**: the SSM command runs as root; `flock` creates the lock file if absent.

## Out of Scope

- The portfolio repo, its files, IAM trust extension, deploy key, and Route 53 records (owned by the `dsaavedra-web` rollout).
- Zero-downtime deploys, blue/green, automated rollback, or a dedicated edge reverse proxy (would be the "full decoupling" option; not warranted for one static site).
