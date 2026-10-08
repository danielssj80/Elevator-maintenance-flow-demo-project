// The orchestrator Lambda's effects: SSM, the n8n child process, the seed
// copy. Every decision lives in lib.mjs, which is what the tests cover.
import { spawn } from 'node:child_process';
import { cpSync, existsSync, readFileSync, rmSync } from 'node:fs';

import { GetParametersCommand, SSMClient } from '@aws-sdk/client-ssm';

import { runInvocation, workflowMetricLine } from './lib.mjs';

const N8N_PORT = 5678;
const STOP_DEADLINE_MS = 20_000;

const INGEST_TOKEN_PARAMETER = process.env.INGEST_TOKEN_PARAMETER ?? '/elevator/orchestrator/ingest-token';
const OTEL_ENDPOINT_PARAMETER = process.env.OTEL_ENDPOINT_PARAMETER ?? '/elevator/otel/grafana-otlp-endpoint';
const OTEL_HEADERS_PARAMETER = process.env.OTEL_HEADERS_PARAMETER ?? '/elevator/otel/grafana-otlp-auth';

// Per sandbox. Lambda reuses a sandbox for warm invocations; a rotated token
// reaches the function at its next cold start, or at once with a code update.
let cachedSecrets;

async function readSecrets() {
  if (cachedSecrets) return cachedSecrets;
  const names = [INGEST_TOKEN_PARAMETER, OTEL_ENDPOINT_PARAMETER, OTEL_HEADERS_PARAMETER];
  let values = {};
  try {
    const out = await new SSMClient({}).send(new GetParametersCommand({ Names: names, WithDecryption: true }));
    values = Object.fromEntries((out.Parameters ?? []).map((p) => [p.Name, p.Value]));
  } catch (err) {
    // Reported as a missing token by buildCredentialOverwrite, which names the
    // parameter. The SDK error says why; log it without any value.
    console.error(JSON.stringify({ ssm: 'GetParameters failed', error: err?.name ?? String(err) }));
  }
  const endpoint = values[OTEL_ENDPOINT_PARAMETER];
  const headers = values[OTEL_HEADERS_PARAMETER];
  if (!endpoint || !headers) {
    console.error(JSON.stringify({ otel: 'disabled for this sandbox: OTLP settings unreadable' }));
  }
  const secrets = {
    ingestToken: values[INGEST_TOKEN_PARAMETER],
    otel: endpoint && headers ? { endpoint, headers } : null,
  };
  if (secrets.ingestToken) cachedSecrets = secrets;
  return secrets;
}

function prepareUserFolder() {
  // A fresh SQLite database per invocation, copied from the seed baked at
  // build time: importing per invocation costs ~18 s more (spike).
  const target = process.env.N8N_USER_FOLDER;
  rmSync(target, { recursive: true, force: true });
  cpSync(process.env.N8N_SEED_FOLDER, target, { recursive: true });
}

let logTail = '';

function startN8n(env) {
  logTail = '';
  const child = spawn('n8n', ['start'], { stdio: ['ignore', 'pipe', 'pipe'], env });
  const append = (chunk) => { logTail = (logTail + chunk).slice(-4000); };
  child.stdout.on('data', append);
  child.stderr.on('data', append);
  const exited = new Promise((resolve) => child.on('exit', (code, signal) => resolve({ code, signal })));
  return {
    isAlive: () => child.exitCode === null && child.signalCode === null,
    async stop() {
      if (child.exitCode !== null || child.signalCode !== null) return { graceful: false, ...(await exited) };
      child.kill('SIGTERM');
      const timer = new Promise((resolve) => setTimeout(() => resolve(null), STOP_DEADLINE_MS));
      const result = await Promise.race([exited, timer]);
      if (result) return { graceful: true, ...result };
      // A frozen n8n never reaches its shutdown hook: its spans are lost, and
      // the result says so rather than claiming a flush.
      child.kill('SIGKILL');
      return { graceful: false, ...(await exited) };
    },
  };
}

function memoryPeakMb() {
  for (const f of ['/sys/fs/cgroup/memory.peak', '/sys/fs/cgroup/memory/memory.max_usage_in_bytes']) {
    if (existsSync(f)) return Math.round(Number(readFileSync(f, 'utf8').trim()) / 1048576);
  }
  return null;
}

export async function handler(event, context) {
  // Per invocation: a failure must never quote the previous invocation's log.
  logTail = '';
  try {
    const result = await runInvocation({
      event,
      requestId: context.awsRequestId,
      deps: {
        env: process.env,
        ingestTokenParameter: INGEST_TOKEN_PARAMETER,
        baseUrl: `http://127.0.0.1:${N8N_PORT}`,
        readinessDeadlineMs: 60_000,
        // From the Runtime API's Lambda-Runtime-Deadline-Ms (bootstrap.mjs).
        deadlineAt: context.deadlineMs,
        stopReserveMs: STOP_DEADLINE_MS + 5_000,
        now: Date.now,
        sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
        readSecrets,
        prepareUserFolder,
        startN8n,
        fetch: (url, init) => fetch(url, init),
      },
    });
    // The digest has no execution history to live in: the log is where it is read.
    // An agent node that failed is configured to continue, so the run still
    // "succeeds" (the re-score happened; the digest did not). Say so in the log.
    const degraded = Boolean(result.output && typeof result.output === 'object' && 'error' in result.output);
    console.log(JSON.stringify({ ...result, degraded, memoryPeakMb: memoryPeakMb() }));
    console.log(workflowMetricLine({ workflow: result.workflow, degraded, timestamp: Date.now() }));
    return result;
  } catch (err) {
    const tail = logTail.split('\n').filter((l) => /error|warn/i.test(l)).slice(-6).join(' / ');
    throw new Error(`${err.message}${tail ? ` | n8n log: ${tail}` : ''}`);
  }
}
