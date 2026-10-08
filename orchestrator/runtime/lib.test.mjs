// node --test orchestrator/
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  WORKFLOWS,
  buildChildEnv,
  buildCredentialOverwrite,
  callWebhook,
  isRealWebhookResponse,
  resolveWorkflow,
  runInvocation,
  waitForReadiness,
} from './lib.mjs';

const ROLE_ENV = {
  AWS_ACCESS_KEY_ID: 'ASIAEXAMPLE',
  AWS_SECRET_ACCESS_KEY: 'secret-example',
  AWS_SESSION_TOKEN: 'session-example',
};
const TOKEN = 'x'.repeat(43);
const PARAM = '/elevator/orchestrator/ingest-token';
const noSleep = async () => {};

function response(status, contentType, body = '{}') {
  return {
    status,
    headers: { get: (name) => (name.toLowerCase() === 'content-type' ? contentType : null) },
    text: async () => body,
  };
}

// ── resolveWorkflow ──────────────────────────────────────────────────────────

test('known workflows resolve to their slug', () => {
  for (const slug of WORKFLOWS) assert.equal(resolveWorkflow({ workflow: slug }), slug);
});

test('an unknown workflow is refused, naming the accepted ones', () => {
  for (const event of [{}, { workflow: 'telemetry' }, { workflow: '' }, null]) {
    assert.throws(() => resolveWorkflow(event), /unknown workflow.*telemetry-ingest, daily-inference-and-digest/);
  }
});

// ── buildCredentialOverwrite ─────────────────────────────────────────────────

test('the overwrite carries the token header and the role session', () => {
  const data = JSON.parse(
    buildCredentialOverwrite({ ingestToken: TOKEN, ingestTokenParameter: PARAM, env: ROLE_ENV }),
  );
  assert.deepEqual(data.httpHeaderAuth, { name: 'X-Ingest-Token', value: TOKEN });
  assert.deepEqual(data.aws, {
    accessKeyId: 'ASIAEXAMPLE',
    secretAccessKey: 'secret-example',
    sessionToken: 'session-example',
  });
});

test('a missing or blank token fails naming the parameter, never a value', () => {
  for (const ingestToken of [undefined, null, '', '   ']) {
    assert.throws(
      () => buildCredentialOverwrite({ ingestToken, ingestTokenParameter: PARAM, env: ROLE_ENV }),
      (err) => err.message.includes(PARAM) && !err.message.includes('ASIAEXAMPLE'),
    );
  }
});

test('missing role credentials fail by name', () => {
  const env = { ...ROLE_ENV };
  delete env.AWS_SESSION_TOKEN;
  assert.throws(
    () => buildCredentialOverwrite({ ingestToken: TOKEN, ingestTokenParameter: PARAM, env }),
    /AWS_SESSION_TOKEN/,
  );
});

// ── buildChildEnv ────────────────────────────────────────────────────────────

test('OTel settings reach the child only when they were read', () => {
  const withOtel = buildChildEnv({
    baseEnv: { A: '1' },
    credentialOverwrite: '{}',
    otel: { endpoint: 'https://otlp.example', headers: 'Authorization=Basic abc=' },
  });
  assert.equal(withOtel.N8N_OTEL_ENABLED, 'true');
  assert.equal(withOtel.N8N_OTEL_EXPORTER_OTLP_HEADERS, 'Authorization=Basic abc=');
  assert.equal(withOtel.CREDENTIALS_OVERWRITE_DATA, '{}');
  assert.equal(withOtel.A, '1');

  const without = buildChildEnv({ baseEnv: {}, credentialOverwrite: '{}', otel: null });
  assert.equal(without.N8N_OTEL_ENABLED, 'false');
  assert.equal(without.N8N_OTEL_EXPORTER_OTLP_HEADERS, undefined);
});

// ── isRealWebhookResponse ────────────────────────────────────────────────────

test('only 200 with a JSON body counts as the workflow having run', () => {
  assert.equal(isRealWebhookResponse(200, 'application/json; charset=utf-8'), true);
  assert.equal(isRealWebhookResponse(200, 'text/html; charset=utf-8'), false); // "n8n is starting up"
  assert.equal(isRealWebhookResponse(200, undefined), false);
  assert.equal(isRealWebhookResponse(503, 'application/json'), false);
  assert.equal(isRealWebhookResponse(500, 'application/json'), false);
});

// ── waitForReadiness ─────────────────────────────────────────────────────────

test('readiness waits past a non-JSON 200 and a refused connection', async () => {
  const answers = [
    () => { throw new Error('ECONNREFUSED'); },
    () => response(200, 'text/html'),
    () => response(503, 'application/json'),
    () => response(200, 'application/json'),
  ];
  let calls = 0;
  await waitForReadiness({
    fetchFn: async () => answers[calls++](),
    url: 'http://127.0.0.1:5678/healthz/readiness',
    isAlive: () => true,
    sleep: noSleep,
    deadlineMs: 60_000,
  });
  assert.equal(calls, 4);
});

test('readiness aborts as soon as n8n has exited', async () => {
  await assert.rejects(
    waitForReadiness({
      fetchFn: async () => response(503, 'application/json'),
      url: 'u',
      isAlive: () => false,
      sleep: noSleep,
      deadlineMs: 60_000,
    }),
    /exited before it became ready/,
  );
});

test('readiness gives up at the deadline', async () => {
  let t = 0;
  await assert.rejects(
    waitForReadiness({
      fetchFn: async () => response(503, 'application/json'),
      url: 'u',
      isAlive: () => true,
      sleep: async () => { t += 1000; },
      deadlineMs: 5000,
      now: () => t,
    }),
    /not ready within 5000 ms/,
  );
});

// ── callWebhook ──────────────────────────────────────────────────────────────

test('a 404 means not registered yet and is retried; the body is sent', async () => {
  const seen = [];
  const answers = [response(404, 'application/json'), response(200, 'application/json', '{"ok":1}')];
  const result = await callWebhook({
    fetchFn: async (url, init) => { seen.push(JSON.parse(init.body)); return answers.shift(); },
    url: 'u',
    body: { invocationId: 'req-1' },
    sleep: noSleep,
  });
  assert.deepEqual(result, { ok: 1 });
  assert.deepEqual(seen, [{ invocationId: 'req-1' }, { invocationId: 'req-1' }]);
});

test('a "starting up" page is a failure, not a result', async () => {
  await assert.rejects(
    callWebhook({
      fetchFn: async () => response(200, 'text/html', 'n8n is starting up'),
      url: 'u',
      body: {},
      sleep: noSleep,
    }),
    /did not run the workflow: HTTP 200 n8n is starting up/,
  );
});

// ── runInvocation: lifecycle ─────────────────────────────────────────────────

function fakeDeps({ fetchAnswers, secrets = { ingestToken: TOKEN, otel: null } } = {}) {
  const log = [];
  const child = {
    alive: true,
    isAlive() { return this.alive; },
    async stop() { log.push('stop'); this.alive = false; return { graceful: true }; },
  };
  let clock = 0;
  const deps = {
    env: ROLE_ENV,
    ingestTokenParameter: PARAM,
    baseUrl: 'http://127.0.0.1:5678',
    readinessDeadlineMs: 60_000,
    now: () => (clock += 10),
    sleep: noSleep,
    readSecrets: async () => { log.push('secrets'); return secrets; },
    prepareUserFolder: () => log.push('prepare'),
    startN8n: (env) => { log.push('start'); deps.childEnv = env; return child; },
    fetch: async (url) => {
      log.push(url.endsWith('/healthz/readiness') ? 'ready?' : 'webhook');
      return fetchAnswers.shift()();
    },
  };
  return { deps, log, child };
}

test('a successful invocation calls the webhook once and stops n8n before returning', async () => {
  const { deps, log } = fakeDeps({
    fetchAnswers: [() => response(200, 'application/json'), () => response(200, 'application/json', '{"output":"digest"}')],
  });

  const result = await runInvocation({ event: { workflow: 'daily-inference-and-digest' }, requestId: 'req-9', deps });

  assert.deepEqual(log, ['secrets', 'prepare', 'start', 'ready?', 'webhook', 'stop']);
  assert.deepEqual(result.output, { output: 'digest' });
  assert.equal(result.requestId, 'req-9');
  assert.equal(result.spansFlushed, true);
  assert.equal(JSON.parse(deps.childEnv.CREDENTIALS_OVERWRITE_DATA).httpHeaderAuth.value, TOKEN);
});

test('an unknown workflow starts nothing and reads no secret', async () => {
  const { deps, log } = fakeDeps({ fetchAnswers: [] });
  await assert.rejects(runInvocation({ event: { workflow: 'nope' }, requestId: 'r', deps }), /unknown workflow/);
  assert.deepEqual(log, []);
});

test('a missing token fails before n8n starts', async () => {
  const { deps, log } = fakeDeps({ fetchAnswers: [], secrets: { ingestToken: '', otel: null } });
  await assert.rejects(runInvocation({ event: { workflow: 'telemetry-ingest' }, requestId: 'r', deps }), new RegExp(PARAM));
  assert.deepEqual(log, ['secrets']);
});

test('a failed webhook still stops n8n before the error is returned', async () => {
  const { deps, log, child } = fakeDeps({
    fetchAnswers: [() => response(200, 'application/json'), () => response(500, 'application/json', '{"message":"boom"}')],
  });
  await assert.rejects(runInvocation({ event: { workflow: 'telemetry-ingest' }, requestId: 'r', deps }), /HTTP 500/);
  assert.equal(log.at(-1), 'stop');
  assert.equal(child.isAlive(), false);
});

test('a readiness failure still stops n8n', async () => {
  let t = 0;
  const { deps, log } = fakeDeps({ fetchAnswers: Array(100).fill(() => response(503, 'application/json')) });
  deps.now = () => (t += 30_000);
  await assert.rejects(runInvocation({ event: { workflow: 'telemetry-ingest' }, requestId: 'r', deps }), /not ready/);
  assert.equal(log.at(-1), 'stop');
});

// ── workflowMetricLine ───────────────────────────────────────────────────────

test('a finished run emits one EMF line per workflow, degraded runs flagged', async () => {
  const { workflowMetricLine } = await import('./lib.mjs');
  const line = JSON.parse(workflowMetricLine({ workflow: 'daily-inference-and-digest', degraded: true, timestamp: 1_700_000_000_000 }));

  const [directive] = line._aws.CloudWatchMetrics;
  assert.equal(line._aws.Timestamp, 1_700_000_000_000);
  assert.equal(directive.Namespace, 'Elevator/Orchestrator');
  assert.deepEqual(directive.Dimensions, [['Workflow']]);
  assert.deepEqual(directive.Metrics.map((m) => m.Name).sort(), ['WorkflowDegraded', 'WorkflowSucceeded']);
  assert.equal(line.Workflow, 'daily-inference-and-digest');
  assert.equal(line.WorkflowSucceeded, 1);
  assert.equal(line.WorkflowDegraded, 1);

  const clean = JSON.parse(workflowMetricLine({ workflow: 'telemetry-ingest', degraded: false, timestamp: 1 }));
  assert.equal(clean.WorkflowDegraded, 0);
});

// ── Deadline: always leave time to stop n8n gracefully ───────────────────────

test('readiness and the webhook stop early enough to leave the stop reserve', async () => {
  let clock = 0;
  const seenSignals = [];
  const { deps, log } = fakeDeps({
    fetchAnswers: [() => response(200, 'application/json'), () => response(200, 'application/json')],
  });
  deps.now = () => clock;
  deps.deadlineAt = 40_000; // the Lambda's deadline, 40 s away
  deps.stopReserveMs = 25_000;
  const fetchAnswers = [() => response(200, 'application/json'), () => response(200, 'application/json')];
  deps.fetch = async (url, init) => {
    log.push(url.endsWith('/healthz/readiness') ? 'ready?' : 'webhook');
    if (init?.signal) seenSignals.push(init.signal);
    return fetchAnswers.shift()();
  };

  await runInvocation({ event: { workflow: 'telemetry-ingest' }, requestId: 'r', deps });

  assert.equal(seenSignals.length, 1, 'the webhook call must carry an abort signal');
  assert.equal(seenSignals[0].aborted, false);
});

test('readiness gives up at the Lambda deadline minus the stop reserve, not at 60 s', async () => {
  let clock = 0;
  const { deps, log } = fakeDeps({ fetchAnswers: Array(1000).fill(() => response(503, 'application/json')) });
  deps.now = () => (clock += 1_000);
  deps.sleep = async () => {};
  deps.deadlineAt = 30_000;
  deps.stopReserveMs = 25_000;

  await assert.rejects(
    runInvocation({ event: { workflow: 'telemetry-ingest' }, requestId: 'r', deps }),
    /not ready within/,
  );
  // ~5 s of budget at 1 s per probe, not 60.
  assert.ok(log.filter((l) => l === 'ready?').length <= 6, log.length);
  assert.equal(log.at(-1), 'stop');
});

test('a forced stop is reported as spans lost, not flushed', async () => {
  const { deps, child } = fakeDeps({
    fetchAnswers: [() => response(200, 'application/json'), () => response(200, 'application/json')],
  });
  child.stop = async () => ({ graceful: false });

  const result = await runInvocation({ event: { workflow: 'telemetry-ingest' }, requestId: 'r', deps });

  assert.equal(result.spansFlushed, false);
});
