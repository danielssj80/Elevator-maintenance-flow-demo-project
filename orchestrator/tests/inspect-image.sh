#!/bin/sh
# Runs INSIDE the orchestrator image (see image.test.mjs). Prints one JSON
# document describing what the image would run with, for the test to assert on.
set -e
cp -r "$N8N_SEED_FOLDER" /tmp/inspect
export N8N_USER_FOLDER=/tmp/inspect
n8n export:workflow --all --output=/tmp/workflows.json >/dev/null 2>&1
# --decrypted with the seed's own key: the point is to see what is stored.
n8n export:credentials --all --decrypted --output=/tmp/credentials.json >/dev/null 2>&1
node /inspect/summarise.mjs
