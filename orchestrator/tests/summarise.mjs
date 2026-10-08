// Inside the image: summarise seeded workflows, credentials and any secret-like
// strings in the files the image adds and in its environment.
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

const SECRET_PATTERNS = {
  awsAccessKey: /\b(AKIA|ASIA)[0-9A-Z]{16}\b/,
  otlpBasicAuth: /Authorization=Basic\s+\S/,
  grafanaCloudToken: /\bglc_[A-Za-z0-9+/=]{20,}/,
  localDevIngestToken: /local-dev-ingest-token/,
};

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    if (name === 'node_modules') continue;
    const path = join(dir, name);
    const st = statSync(path);
    if (st.isDirectory()) walk(path, out);
    else if (st.size < 5_000_000) out.push(path);
  }
  return out;
}

const hits = [];
for (const path of [...walk('/opt/n8n-seed'), ...walk('/opt/runtime')]) {
  const text = readFileSync(path, 'latin1');
  for (const [label, re] of Object.entries(SECRET_PATTERNS)) if (re.test(text)) hits.push(`${label} in ${path}`);
}
for (const [key, value] of Object.entries(process.env)) {
  for (const [label, re] of Object.entries(SECRET_PATTERNS)) if (re.test(value)) hits.push(`${label} in env ${key}`);
}

const workflows = JSON.parse(readFileSync('/tmp/workflows.json', 'utf8')).map((wf) => ({
  id: wf.id,
  active: wf.active,
  nodes: wf.nodes.map((n) => ({
    name: n.name, type: n.type, disabled: !!n.disabled, path: n.parameters?.path, url: n.parameters?.url,
  })),
}));
const credentials = JSON.parse(readFileSync('/tmp/credentials.json', 'utf8')).map((c) => ({
  id: c.id, type: c.type, data: c.data,
}));

console.log(JSON.stringify({ workflows, credentials, secretHits: hits, env: {
  N8N_ENCRYPTION_KEY: process.env.N8N_ENCRYPTION_KEY ?? null,
  N8N_OTEL_TRACES_INCLUDE_NODE_SPANS: process.env.N8N_OTEL_TRACES_INCLUDE_NODE_SPANS,
  N8N_AGENTS_TRACING_RECORD_INPUTS: process.env.N8N_AGENTS_TRACING_RECORD_INPUTS,
  N8N_AGENTS_TRACING_RECORD_OUTPUTS: process.env.N8N_AGENTS_TRACING_RECORD_OUTPUTS,
  N8N_BLOCK_ENV_ACCESS_IN_NODE: process.env.N8N_BLOCK_ENV_ACCESS_IN_NODE ?? null,
} }));
