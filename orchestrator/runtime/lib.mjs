// The orchestrator Lambda's decisions, kept free of I/O so `node --test` can
// cover every one of them without Docker, AWS or a network.
//
// One invocation runs one workflow on a short-lived n8n: copy the seed, start
// `n8n start`, wait for real readiness, call the workflow's webhook, stop n8n
// and wait for it to exit (its spans are flushed on shutdown). Every trap the
// spike found is handled here and named where it is handled:
// spikes/n8n-lambda/FINDINGS.md on branch spike/n8n-lambda.

// Slug = webhook path = repository file name (n8n/workflows/<slug>.json).
export const WORKFLOWS = Object.freeze(['telemetry-ingest', 'daily-inference-and-digest']);

export function resolveWorkflow(event) {
  const slug = event?.workflow;
  if (!WORKFLOWS.includes(slug)) {
    throw new Error(
      `unknown workflow ${JSON.stringify(slug)}; expected one of ${WORKFLOWS.join(', ')}`,
    );
  }
  return slug;
}

// CREDENTIALS_OVERWRITE_DATA is keyed by credential TYPE and only fills fields
// that are EMPTY in the stored credential. The seeded placeholders therefore
// hold "" for every secret (asserted by the image tests); a placeholder value
// would win silently and n8n would send it.
export function buildCredentialOverwrite({ ingestToken, ingestTokenParameter, env }) {
  if (typeof ingestToken !== 'string' || ingestToken.trim() === '') {
    // Without this check n8n sends an empty X-Ingest-Token and the execution
    // still reports success: the 401 lands in a node, far from its cause.
    throw new Error(`ingest token is missing or empty (SSM parameter ${ingestTokenParameter})`);
  }
  const missing = ['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN'].filter(
    (name) => !env[name],
  );
  if (missing.length) {
    throw new Error(`function role credentials are missing from the environment: ${missing.join(', ')}`);
  }
  return JSON.stringify({
    httpHeaderAuth: { name: 'X-Ingest-Token', value: ingestToken },
    // The role's credentials are temporary; without the session token Bedrock
    // rejects the signature. resolveAwsCredentials in 2.37.6 passes it on only
    // when temporaryCredentials is true, which the placeholder sets.
    aws: {
      accessKeyId: env.AWS_ACCESS_KEY_ID,
      secretAccessKey: env.AWS_SECRET_ACCESS_KEY,
      sessionToken: env.AWS_SESSION_TOKEN,
    },
  });
}

// The environment n8n starts with. Secrets go to the child only, never into
// the function configuration or the image.
export function buildChildEnv({ baseEnv, credentialOverwrite, otel }) {
  const env = { ...baseEnv, CREDENTIALS_OVERWRITE_DATA: credentialOverwrite };
  if (otel) {
    env.N8N_OTEL_ENABLED = 'true';
    env.N8N_OTEL_EXPORTER_OTLP_ENDPOINT = otel.endpoint;
    env.N8N_OTEL_EXPORTER_OTLP_HEADERS = otel.headers;
  } else {
    // No telemetry is better than no ingest: run without exporting.
    env.N8N_OTEL_ENABLED = 'false';
  }
  return env;
}

function isJson(contentType) {
  return (contentType ?? '').toLowerCase().includes('application/json');
}

// While starting, n8n answers the webhook with 200 text/html "n8n is starting
// up". A status check alone would record that as a successful run.
export function isRealWebhookResponse(status, contentType) {
  return status === 200 && isJson(contentType);
}

// /healthz answers 200 as soon as the HTTP server is up, long before
// workflows are active. /healthz/readiness waits for the database and
// activation, and a JSON body rules out the start-up page.
export async function waitForReadiness({ fetchFn, url, isAlive, sleep, deadlineMs, now = Date.now }) {
  const deadline = now() + deadlineMs;
  for (;;) {
    if (!isAlive()) throw new Error('n8n exited before it became ready');
    try {
      const response = await fetchFn(url);
      if (response.status === 200 && isJson(response.headers.get('content-type'))) return;
    } catch {
      // Not listening yet.
    }
    if (now() >= deadline) throw new Error(`n8n was not ready within ${deadlineMs} ms`);
    await sleep(200);
  }
}

// Readiness can precede webhook registration by a few hundred ms; only a 404
// means "not registered yet". Anything else is the answer.
export async function callWebhook({ fetchFn, url, body, sleep, maxNotRegistered = 50 }) {
  for (let attempt = 0; ; attempt++) {
    const response = await fetchFn(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (response.status !== 404 || attempt >= maxNotRegistered) {
      const text = await response.text();
      if (!isRealWebhookResponse(response.status, response.headers.get('content-type'))) {
        throw new Error(`webhook did not run the workflow: HTTP ${response.status} ${text.slice(0, 200)}`);
      }
      return JSON.parse(text);
    }
    await sleep(200);
  }
}

// The whole invocation, with every effect injected. `stop` runs on every path:
// an n8n left alive in a reused sandbox answers the next invocation's
// readiness probe and turns its start-up into a lie.
export async function runInvocation({ event, requestId, deps }) {
  const workflow = resolveWorkflow(event);
  const started = deps.now();
  const secrets = await deps.readSecrets();
  const credentialOverwrite = buildCredentialOverwrite({
    ingestToken: secrets.ingestToken,
    ingestTokenParameter: deps.ingestTokenParameter,
    env: deps.env,
  });
  const childEnv = buildChildEnv({ baseEnv: deps.env, credentialOverwrite, otel: secrets.otel });

  deps.prepareUserFolder();
  const child = deps.startN8n(childEnv);
  let output;
  let stopped;
  try {
    await waitForReadiness({
      fetchFn: deps.fetch,
      url: `${deps.baseUrl}/healthz/readiness`,
      isAlive: () => child.isAlive(),
      sleep: deps.sleep,
      deadlineMs: deps.readinessDeadlineMs,
      now: deps.now,
    });
    output = await callWebhook({
      fetchFn: deps.fetch,
      url: `${deps.baseUrl}/webhook/${workflow}`,
      body: { invocationId: requestId },
      sleep: deps.sleep,
    });
  } finally {
    // Before returning, on success and on failure alike: spans are exported in
    // n8n's shutdown hook, and Lambda freezes the sandbox on return.
    stopped = await child.stop();
  }
  return {
    workflow,
    requestId,
    output,
    spansFlushed: stopped.graceful,
    ms: deps.now() - started,
  };
}
