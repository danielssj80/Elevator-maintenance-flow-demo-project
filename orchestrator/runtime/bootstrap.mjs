// Lambda custom runtime: the Runtime API loop in plain Node. The n8n image is
// hardened (no apk), so aws-lambda-ric cannot be installed; this loop is the
// whole of what it would have provided.
import http from 'node:http';

const api = process.env.AWS_LAMBDA_RUNTIME_API;
const base = '/2018-06-01/runtime';

function request(method, path, body, headers = {}) {
  const [host, port] = api.split(':');
  return new Promise((resolve, reject) => {
    const req = http.request(
      { host, port, path, method, headers: { 'content-type': 'application/json', ...headers } },
      (res) => {
        let data = '';
        res.on('data', (chunk) => (data += chunk));
        res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body: data }));
      },
    );
    req.on('error', reject);
    if (body !== undefined) req.write(body);
    req.end();
  });
}

function errorBody(err) {
  return JSON.stringify({ errorMessage: String(err?.message ?? err), errorType: err?.name ?? 'Error' });
}

let handler;
try {
  ({ handler } = await import('./handler.mjs'));
} catch (err) {
  await request('POST', `${base}/init/error`, errorBody(err), {
    'Lambda-Runtime-Function-Error-Type': 'Runtime.InitError',
  });
  process.exit(1);
}

for (;;) {
  const next = await request('GET', `${base}/invocation/next`);
  const requestId = next.headers['lambda-runtime-aws-request-id'];
  try {
    const result = await handler(JSON.parse(next.body || '{}'), { awsRequestId: requestId });
    await request('POST', `${base}/invocation/${requestId}/response`, JSON.stringify(result));
  } catch (err) {
    console.error(JSON.stringify({ requestId, error: String(err?.message ?? err) }));
    await request('POST', `${base}/invocation/${requestId}/error`, errorBody(err), {
      'Lambda-Runtime-Function-Error-Type': 'Unhandled',
    });
  }
}
