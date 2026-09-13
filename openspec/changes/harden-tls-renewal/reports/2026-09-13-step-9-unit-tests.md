# Step 9 Report — Unit Tests and DB State

- Date: 2026-09-13
- Change: harden-tls-renewal

## Commands executed

```bash
backend/venv/bin/python -m pytest tests/unit/test_tls_renewal_config.py -q --confcutdir=tests/unit
backend/venv/bin/ruff check .
backend/venv/bin/shellcheck deploy/tls/*.sh scripts/check-tls-expiry.sh
```

## Results

- Targeted tests: **13 passed**, 0 failed, 0 skipped — and no test in the file is
  skippable: the `skipif` guards that would have made a missing installer read as
  a pass were removed before implementation began, because a skipped guard is
  indistinguishable from a passing one and this change exists because of a
  failure that looked like a success.
- `ruff check .`: **All checks passed.** One finding fixed on the way (`pytest`
  became an unused import once the skips were removed).
- `shellcheck`: clean on all four shell files. One finding fixed: SC1007 on
  `CDPATH= cd`, now `CDPATH='' cd`.

## The full suite runs in CI, and why

`backend/tests/conftest.py:43` defines `setup_test_db` as
`scope="session", autouse=True`, so **every** test in this suite requires a
reachable PostgreSQL. Without one each test errors in setup after a 60-second
asyncio timeout — 190 errors, none of them related to this change. That is a
property of the repository, not of this branch.

This environment cannot provide that database:

- Docker Desktop is not running (`docker info` returns the WSL2 documentation
  link), so the documented "test in Docker" path is unavailable.
- The system interpreter is Python **3.14.4**, while the project pins
  `pydantic==2.10.3` and builds on `python:3.12-slim`. `pip install -r
  requirements.txt` fails building `pydantic-core` from source for 3.14.

So the authoritative full-suite evidence is the CI run on the pull request, which
is the pinned environment: `.github/workflows/ci.yml` uses
`actions/setup-python@v5` with `python-version: "3.12"`, installs
`requirements.txt` + `requirements-dev.txt` exactly as pinned, runs `ruff check .`
and `python -m pytest tests/ -q` against a `postgres:16-alpine` service. The
targeted file above was run locally with `--confcutdir=tests/unit`, which is what
lets it execute without the database-backed conftest — it needs no database,
because it reads configuration files and runs a shell script.

**CI result on the PR: see `2026-09-13-step-13-real-configuration.md`.**

## DB state

No baseline capture was possible or meaningful: this change contains **no
application code**. Verified rather than asserted, over the full branch diff
against `origin/main`:

```
$ git diff --name-only origin/main...HEAD
.github/workflows/deploy.yml
.github/workflows/tls-expiry-check.yml
backend/tests/unit/test_tls_renewal_config.py
deploy/tls/README.md
deploy/tls/certbot-renew.service
deploy/tls/certbot-renew.timer
deploy/tls/install-renewal.sh
deploy/tls/reload-nginx-deploy-hook.sh
docs/deployment.md
scripts/check-tls-expiry.sh
openspec/...  (change artifacts, reports and the two synced specs)
```

- No file under `backend/app/` is touched — no ORM model, no schema, no endpoint.
- No new revision in `backend/alembic/versions/`, so there is no migration to
  apply and nothing for `alembic check` to report.
- No test in this change writes to a database, and none of the production checks
  in step 10 issues a mutating request.

## Outcome

PASS locally for everything runnable here; full-suite and lint confirmation from
the CI run recorded in the step 13 report.
