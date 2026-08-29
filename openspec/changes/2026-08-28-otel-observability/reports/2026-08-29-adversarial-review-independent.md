# Adversarial Review (independent) — otel-observability

- **Date**: 2026-08-29
- **Change**: 2026-08-28-otel-observability
- **Reviewer**: a separate agent session, given no context beyond the repo and
  the running stack. It ran 7 source mutations and returned **FAIL**
  (1 Blocker, 6 Majors, 12 Minors).

The author's own earlier review (`2026-08-29-adversarial-review.md`) returned
PASS WITH GAPS and is superseded by this one. It missed everything below.

## Findings confirmed by independent re-verification, and their fixes

Every claim was re-checked before acting on it.

### Blocker — console logging destroyed; export failures unobservable

The OTLP log handler was attached to the root logger *before*
`LoggingInstrumentor(set_logging_format=True)` ran `logging.basicConfig`, which
is a no-op once root has any handler. Root ended with **two OTel handlers and
zero StreamHandlers**, so application logs existed only inside the OTLP
pipeline — invisible exactly when that pipeline is what broke. A regression
against `main`, where `logging.lastResort` still put warnings on stderr.

*Verified*: probe showed `[LoggingHandler, LoggingHandler]`, zero StreamHandlers;
`docker compose logs backend | grep -c "Bedrock briefing generation failed"` → 0,
though Loki held the record. Those lines had been visible earlier in the same
session, so the author's own log-export fix caused it.

**Fixed**: `basicConfig(..., force=True)` before any OTLP wiring. Verified after
rebuild: the warning is back on stdout.

### Major — every log record exported twice

Two handlers on root sharing one provider: one added explicitly, one by
`LoggingInstrumentor`. **Fixed** by letting the instrumentor own the single
handler. Verified in Loki: the same line at the same nanosecond appeared twice
before, once after.

### Major — the SQLAlchemy guard had no teeth, and the documented rule was wrong

Removing `engine=db_engine.sync_engine` left all tests green. The premise —
stated in `design.md` D3, the module docstring, several commit messages, the
step reports and, worst, `docs/backend-standards.md` as a project standard —
was **factually wrong**: `_instrument` also patches `Engine.connect` class-wide,
so a pre-built engine still emits `connect` spans.

*Measured on 0.65b0, one query*:

| | spans | with `db.statement` |
|---|---|---|
| with `engine=` | `connect`, `SELECT` | 1 |
| without | `connect` | 0 |

The real failure is losing **per-statement** spans while connection spans keep
arriving and the instrumentation looks healthy. The test asserted on
`db.system`, which the `connect` span also carries, so it caught nothing.

**Fixed**: corrected in all four places, and the test now asserts on
`db.statement`. Re-ran the mutation: it now **fails**.

Root cause of the mistake: the author verified the concurrency test's teeth by
reverting the implementation, and asserted this one's teeth without ever running
the equivalent mutation.

### Major — three metric-wiring mutations undetected

Removing the gauge callbacks, removing the service's `record_briefing_request`
calls, and removing `register_instruments()` from the lifespan all left the
suite green. The tests called callback *functions* directly, proving they work
but nothing about whether they were registered against a provider.

**Fixed**: new tests collect through the real `InMemoryMetricReader`; the
briefing test drives `BriefingService` rather than the recorder; the lifespan
test spies on `register_instruments` rather than looking for metrics that an
earlier test may already have registered. All three mutations now fail.

### Major — `app/main.py` lifespan uncovered (58%)

Removing `refresh_task.cancel()` went undetected. **Fixed**: a test drives
`lifespan(app)` directly. Coverage 58% → **97%**. The test is wrapped in
`asyncio.timeout(10)` because without the cancel the lifespan never returns and
would hang the suite instead of failing it.

### Major — reconfiguration after shutdown silently discarded every span

`shutdown_telemetry()` resets `_tracer_provider = None`, defeating the
already-configured guard; the next `configure_telemetry` builds a provider the
global API refuses to adopt, so `get_tracer()` keeps writing into the
shut-down one. Reachable via `uvicorn --reload`. **Fixed**: a second
configuration now raises with an explanatory message instead of failing silently.

### Major — Collector overwrote the application's environment attribute

`resource/env` used `action: upsert`, making `DEPLOYMENT_ENVIRONMENT` dead.
**Fixed** to `insert`. Verified with a distinct value: `verify-insert-not-upsert`
now survives to Prometheus. A first check appeared to fail because the Collector
only reads its mounted config at startup and had not been recreated.

### Minors fixed

- `design.md` claimed a redaction processor that does not exist — claim dropped.
- `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` pinned to `false` rather
  than relying on a default; the botocore instrumentation emits GenAI **log
  records** the spec's "any span it creates" wording did not cover. Spec widened
  to "any signal it exports".
- `FleetHealthService`'s docstring claimed the dashboard and the API can never
  disagree. They do, by design — corrected to say so and point at the backlog task.
- `_EXCLUDED_URLS` anchored to `^/health$`; a bare `health` would silently drop
  tracing for a future `/api/fleet-health`.
- `anyio` pinned; it was used directly but present only transitively.
- Unjustified `Any` annotations replaced with `Counter`, `Histogram`,
  `async_sessionmaker[AsyncSession]`, `float`, and concrete provider types.
- The refresh loop now runs inside a `fleet.refresh` span; its query was
  producing an unparented root `SELECT` trace every 60 seconds.
- Concurrency test margin widened from 60 ms to 250 ms of headroom.
- A collector-health row added to the fleet-health dashboard, with
  `or vector(0)` so a never-incremented drop counter renders `0` rather than
  "No data" — otherwise healthy and not-collecting look identical.

## Accepted, not fixed

- **Layering**: `app/core/metrics.py` imports repository and service modules
  inside a function to break a real cycle, because `FleetHealthSnapshot` lives
  in `core/`. Moving the domain type into the service layer is the clean fix and
  is deferred rather than done blind at the end of a change.
- **httpx / default-engine branches** remain uncovered: httpx is dev-only, and
  the default-engine path is production-only by construction.

## Test isolation defects found along the way

Three separate tests tore down state shared with the whole session — the
briefing cache, then `shutdown_telemetry()` detaching the session's providers,
then the lifespan test doing the same. Each passed in isolation and broke others
by ordering. Recorded because the pattern recurred three times.

## Result

| | Before | After |
|---|---|---|
| Tests | 85 | 90 |
| Total coverage | 94% | 96% |
| `app/main.py` | 58% | 97% |
| Mutations caught | 0 of 4 | 4 of 4 |

## Verdict

Independent verdict was **FAIL**. The Blocker and all six Majors are fixed and
each fix independently verified. A third review pass is advisable before merge,
since the fixes have not themselves been independently reviewed.
