# Adversarial Review, round 3 (independent) — otel-observability

- **Date**: 2026-08-29
- **Reviewer**: a third agent session with no prior context. Ran **21 source
  mutations** against a scratch copy. Verdict: **FAIL** — 2 Blockers, 4 Majors.

## The finding that matters most

Both Blockers and two of the four Majors were **regressions or false claims
introduced by round 2's own fixes**, which nobody independent had reviewed.
Round 2 was itself a response to round 1 having missed everything.

That is the pattern worth recording: each unreviewed batch of fixes introduced
new defects of the same class it was fixing, and only mutation testing found
them. Reading the diff did not.

## Blockers — both confirmed, both fixed

### The `/health` exclusion was dead

Round 2 "tightened" `_EXCLUDED_URLS` from `"health"` to `r"^/health$"`. The
instrumentation matches the regex against the **full URL**
(`http://host:8000/health`), not the path, so a leading `^` can never match. The
exclusion stopped working entirely.

Verified against `opentelemetry.util.http.parse_excluded_urls`:

| pattern | `/health` | `/api/fleet-health` |
|---|---|---|
| `health` | matches | matches (over-matches) |
| `^/health$` | no | no (matches nothing) |
| `/health$` | matches | no (correct) |

Live evidence: `http_server_request_duration_seconds_count{http_route="/health"}`
had reached **548** — a healthcheck every 10 seconds, traced, metered, and with
the cloud overlay active, billed to Grafana Cloud.

**Fixed** to `r"/health$"`. Verified live: the counter froze across 60 seconds
of healthchecks and Tempo returns zero `/health` traces.

### The test suite shipped its own logs to the production service name

`configure_telemetry()` had seams for spans and metrics but none for logs, so it
always built a real `OTLPLogExporter`. The suite therefore opened a live OTLP
connection and published every log record it produced under
`service_name="elevator-backend"` — indistinguishable from real traffic. Loki
held lines like `HTTP Request: GET http://test/api/elevators/DOES-NOT-EXIST/briefing`.

This directly contradicted the requirement's own stated purpose: *"so that CI
runs and the test suite are unaffected by the absence of a Collector."*

**Fixed**: a `log_record_processor` seam, with `SimpleLogRecordProcessor(InMemoryLogExporter())`
in `conftest`. Verified: zero leaked lines after a full run.

## Majors — all four confirmed and fixed

- **The Collector-health dashboard row read a different Collector.** Nothing
  scraped `otel-collector:8888`; the `otelcol_*` series in Prometheus came from
  LGTM's bundled collector. The panel added in round 2 specifically to catch a
  silent cloud-export failure was itself silent. **Fixed** with a
  `prometheus/self` receiver, restated in the cloud overlay because merge
  replaces lists. Verified: `otlp_http/local` and `otlp_http/grafana_cloud` now
  appear in Prometheus.
- **Removing `refresh_task.cancel()` still passed.** Round 2's lifespan test
  relied on an outer `asyncio.timeout` firing, but the lifespan's own
  `contextlib.suppress(asyncio.CancelledError)` swallows that cancellation. The
  only symptom was the suite taking 16s instead of 6s. **Fixed** by running the
  exit as a shielded task; the mutation now produces 14 failures in 8.8s.
- **Removing the log record processor still passed.** A `LoggerProvider` with
  zero processors satisfies both "a provider exists" and "a handler is on root".
  **Fixed** with a test that emits a marker and asserts it reaches an exporter.
- **The lifespan test committed seed data into the shared test database.** It
  ran the real `lifespan`, and therefore the real `seed_database`, inserting 100
  elevators mid-session. Green only because pytest collected integration tests
  first. **Fixed** by patching `seed_database`; verified with unit-first
  ordering.

## Minors fixed

Three task checkboxes claimed more than was verified and now say what was
actually done: 9.5 (the failure counter has no series until it first
increments, so absence was read as zero), 10.3 (token usage and latency are a
text panel pointing at traces, not graph panels), 13.4 (token counts could not
be verified — the local stack has no AWS credentials, so every briefing takes
the fallback path).

Also: the comment around `set_logging_format=True` now says that it is
effectively inert for formatting, since `basicConfig` already ran; and tests
were added asserting the botocore and SQLAlchemy instrumentors are actually
installed, neither of which any behavioural test covered.

## Confirmed correct by independent re-measurement

The reviewer re-measured the SQLAlchemy binding claim corrected in round 2 —
bound gives `['connect','SELECT']` with one `db.statement` span, unbound gives
`['connect']` and none — and confirmed the corrected wording is accurate and the
guarding test now fails under mutation. It also confirmed the GenAI
content-capture variable name and default against the installed library source,
the `LoggingInstrumentor` handler behaviour, absence of prompt or PII content in
spans and in the exported Bedrock traceback, absence of secrets in the branch
history, correct metric cardinality, and working cloud fan-out.

## Result

| | Round 2 end | Round 3 end |
|---|---|---|
| Tests | 90 | 95 |
| Coverage | 96% | 96% |
| `app/main.py` | 97% | 100% |
| Round-3 mutations caught | 0 of 4 | 4 of 4 |

## Carried forward, not fixed

- The unreachable-Collector spec scenario still has no automated test (open
  since round 1). The behaviour was verified manually.
- `app/core/metrics.py` still imports repository and service modules inside a
  function to break a cycle caused by `FleetHealthSnapshot` living in `core/`.
  Moving the domain type into the service layer is the clean fix.
- Loki holds test-suite log streams emitted before the leak was fixed. They age
  out with retention.
- The reconfiguration guard added in round 2 has no test and its stated
  reachability (`uvicorn --reload`) is questionable, since that restarts a
  subprocess.

## Verdict

Independent verdict was **FAIL**. Both Blockers and all four Majors are fixed,
each verified by re-running the mutation or by measuring the live stack.

A fourth independent pass is the consistent recommendation, because this round's
fixes are — again — unreviewed, and that is exactly the condition that produced
this round's Blockers.
