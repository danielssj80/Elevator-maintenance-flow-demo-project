# Step 9 Report — Grafana Cloud Delivery

- **Date**: 2026-08-29
- **Change**: 2026-08-28-otel-observability

## Commands Executed

```bash
# Credentials checked directly against the gateway before involving the Collector
curl -s -w '%{http_code}' -u "${GRAFANA_CLOUD_INSTANCE_ID}:${GRAFANA_CLOUD_API_TOKEN}" \
  -H 'Content-Type: application/json' -d '{"resourceSpans":[]}' \
  "${GRAFANA_CLOUD_OTLP_ENDPOINT}/v1/traces"

docker compose -f docker-compose.yml -f docker-compose.cloud.yml up -d --force-recreate otel-collector
curl -s http://localhost:8888/metrics | grep otelcol_exporter_
```

## Results

Dual export confirmed, region `prod-eu-west-2`:

| Exporter | Spans sent | Metric points sent | Failures |
|---|---|---|---|
| `otlp_http/grafana_cloud` | 55 | 52 | 0 |
| `otlp_http/local` | 55 | 52 | 0 |

`otelcol_exporter_send_failed_spans` and `..._metric_points` have no series at
all for either exporter, which for an OpenTelemetry counter means it never
incremented. Zero `Exporting failed` lines in the Collector log.

Direct gateway probe returns `200 {"partialSuccess":{}}`.

## Two configuration faults found, in the order they appeared

Both are worth recording because both fail in ways that look like something
else.

**1. The endpoint carried a signal path.** `GRAFANA_CLOUD_OTLP_ENDPOINT` was set
to a URL ending in `/v1/traces`. The Collector appends the signal path itself,
so requests went to `.../v1/traces/v1/traces`. This is exactly the base-versus-
full ambiguity documented in `docs/backend-standards.md`, which surfaced in
practice within the hour. Corrected to the base URL.

**2. The first token was rejected.** After the URL was fixed the gateway
returned `401 {"error":"authentication error: invalid token"}`. Credential
*shape* was correct — 7-digit numeric instance ID, 172-character `glc_` token,
no whitespace — so shape checks were not enough to catch it. "invalid token"
rather than a 403 about scopes indicated the gateway could not resolve the token
at all, pointing at a wrong-organisation or wrong-region access policy rather
than a permissions problem. A token regenerated from the stack's own OTLP
connection page worked immediately.

## Why this step justified the design

While the cloud exporter was returning 401 for every batch, the local pipeline
kept delivering normally and every Grafana dashboard looked healthy. That is the
precise failure mode the Collector self-telemetry was configured to expose, and
it was caught by reading `otelcol_exporter_send_failed_spans` rather than by
noticing missing data. Without `service.telemetry.metrics.readers` bound to
`0.0.0.0:8888`, this would have been invisible.

## Outcome

**PASS**
