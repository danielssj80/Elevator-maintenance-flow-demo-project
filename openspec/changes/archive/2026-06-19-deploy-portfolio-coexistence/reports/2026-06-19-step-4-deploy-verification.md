# Step 4 Report — Deploy Verification

- Date: 2026-06-19
- Change: deploy-portfolio-coexistence

## Scope Note
No HTTP endpoints change. "Endpoint testing" maps to verifying the modified deploy
command's logic locally, plus the workflow's own post-deploy smoke check once merged.
The full coexistence assertion (nginx keeps the apex site across an Elevator deploy)
is verified during the `dsaavedra-web` rollout, once `/opt/portfolio` exists.

## 4.1 — Conditional Compose-file logic (both branches)
Ran the exact `if/then/fi` snippet from `deploy.yml` under `set -eu`:

| `/opt/portfolio/docker-compose.portfolio.yml` | Resulting `$CF` |
|---|---|
| present | `-f docker-compose.prod.yml -f /opt/portfolio/docker-compose.portfolio.yml` |
| absent  | `-f docker-compose.prod.yml` |

- The absent case does **not** abort under `set -e` (confirmed) — the Elevator deploy
  degrades to today's behaviour when the portfolio is not present.

## 4.1 (cont.) — Compose merges volumes additively
Minimal repro (base nginx with one mount + override adding two), `docker-compose config`:

```
target: /etc/nginx/conf.d/default.conf   (base, retained)
target: /usr/share/nginx/portfolio       (override, added)
target: /etc/nginx/conf.d/portfolio.conf (override, added)
```

Confirms the design premise: the override **adds** the portfolio mounts onto nginx's
existing mounts rather than replacing them, so the apex site survives recreation.

## 4.2 — Elevator unaffected (smoke)
The workflow's existing smoke step asserts `https://elevator.dsaavedra.dev/health`
returns 200 after every deploy. The change touches only the Compose-file list and adds
`flock`; the auth, polling, and smoke steps are unchanged.

## 4.3 — Coexistence assertion (deferred)
Cross-reference: the assertion that an Elevator deploy preserves the live apex site is
exercised during the `dsaavedra-web` rollout (portfolio deploy + a subsequent Elevator
deploy with `/opt/portfolio` present).

## 5.1 — E2E (Playwright)
Not applicable — no frontend change.

## Re-verification after adversarial review (Major fix)
Added merged-config validation + Elevator-only fallback and `flock -w 600`.

- **actionlint**: exit 0. During re-verification it caught **SC1078/SC1079** — an
  initial `echo 'WARNING…'` used single quotes *inside* the single-quoted
  `--parameters '…'` block, which would have prematurely closed the string on the
  runner. Fixed to escaped double quotes (`echo \"WARNING…\"`); re-checked exit 0.
- **Embedded JSON**: re-parsed, valid.
- **Three-branch logic** (exact block run under `set -eu` with `docker`/`flock` stubs):
  | Case | Result (`up` file list) |
  |---|---|
  | portfolio absent | `-f docker-compose.prod.yml` |
  | present + config valid | `-f docker-compose.prod.yml -f …/docker-compose.portfolio.yml` |
  | present + config broken | warning emitted, falls back to `-f docker-compose.prod.yml`; `set -e` did **not** abort |

Confirms the Major is closed: a broken co-located config no longer takes Elevator down.

## Outcome
PASS
