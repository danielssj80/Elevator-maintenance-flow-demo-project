# The orchestrator as an AWS Lambda function (production). One invocation runs
# one workflow on a short-lived n8n; see runtime/lib.mjs and
# docs/orchestration.md. Build from the repository root:
#   docker build -f orchestrator/Dockerfile -t elevator-orchestrator .
ARG N8N_IMAGE=n8nio/n8n:2.37.6

# ── SSM client ─────────────────────────────────────────────────────────────────
# The n8n image ships no @aws-sdk/client-ssm. Installed apart from n8n's own
# node_modules so neither can shadow the other.
FROM ${N8N_IMAGE} AS sdk
USER root
WORKDIR /opt/runtime
RUN npm install --omit=dev --no-audit --no-fund --no-save @aws-sdk/client-ssm@3.1132.0 \
 && chown -R node:node /opt/runtime

# ── Seed ──────────────────────────────────────────────────────────────────────
# Workflows imported and published into a SQLite database at build time; each
# invocation copies it to /tmp. No secret is stored: the credentials are
# placeholders with EMPTY secret fields, filled at invocation through
# CREDENTIALS_OVERWRITE_DATA (which only fills empty fields).
FROM ${N8N_IMAGE} AS seed
USER root
RUN mkdir -p /opt/n8n-seed /opt/seed-input && chown -R node:node /opt/n8n-seed /opt/seed-input
USER node
COPY --chown=node:node n8n/workflows/ /opt/seed-src/
COPY --chown=node:node orchestrator/seed/ /opt/seed/
ENV N8N_USER_FOLDER=/opt/n8n-seed DB_TYPE=sqlite N8N_DIAGNOSTICS_ENABLED=false
RUN node /opt/seed/prepare-workflows.mjs /opt/seed-src /opt/seed-input \
 && n8n import:credentials --input=/opt/seed/credentials.json \
 && for f in /opt/seed-input/*.json; do n8n import:workflow --input="$f"; done \
 && n8n publish:workflow --id=elevIngest00001 \
 && n8n publish:workflow --id=elevDigest00001

# ── Function ──────────────────────────────────────────────────────────────────
FROM ${N8N_IMAGE}
COPY --from=seed --chown=node:node /opt/n8n-seed /opt/n8n-seed
COPY --from=sdk /opt/runtime/node_modules /opt/runtime/node_modules
COPY orchestrator/runtime/bootstrap.mjs orchestrator/runtime/handler.mjs orchestrator/runtime/lib.mjs /opt/runtime/

# Non-secret configuration only. Secrets arrive from SSM at invocation.
# N8N_ENCRYPTION_KEY is deliberately unset: the seed's .n8n/config carries the
# key generated at build, which encrypts nothing but empty placeholders.
ENV N8N_SEED_FOLDER=/opt/n8n-seed \
    N8N_USER_FOLDER=/tmp/n8n-home \
    DB_TYPE=sqlite \
    N8N_DIAGNOSTICS_ENABLED=false \
    N8N_PERSONALIZATION_ENABLED=false \
    N8N_VERSION_NOTIFICATIONS_ENABLED=false \
    N8N_BLOCK_ENV_ACCESS_IN_NODE=false \
    ELEVATOR_API_BASE_URL=https://elevator.dsaavedra.dev \
    N8N_ENABLED_MODULES=otel \
    N8N_OTEL_EXPORTER_SERVICE_NAME=n8n-lambda \
    N8N_OTEL_TRACES_PRODUCTION_ONLY=true \
    N8N_OTEL_TRACES_INCLUDE_NODE_SPANS=false \
    N8N_OTEL_TRACES_INJECT_OUTBOUND=true \
    N8N_AGENTS_TRACING_RECORD_INPUTS=false \
    N8N_AGENTS_TRACING_RECORD_OUTPUTS=false \
    GENERIC_TIMEZONE=Europe/Madrid \
    TZ=Europe/Madrid

ENTRYPOINT ["node", "/opt/runtime/bootstrap.mjs"]
