// The built orchestrator image, inspected from inside. Skipped unless
// ORCHESTRATOR_IMAGE names an image (CI builds one and sets it):
//   ORCHESTRATOR_IMAGE=elevator-orchestrator:local node --test "orchestrator/**/*.test.mjs"
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const image = process.env.ORCHESTRATOR_IMAGE;
const here = dirname(fileURLToPath(import.meta.url));

let summary;
function inspect() {
  summary ??= JSON.parse(
    execFileSync('docker', [
      'run', '--rm', '--read-only', '--tmpfs', '/tmp:exec', '-v', `${here}:/inspect:ro`,
      '--entrypoint', 'sh', image, '/inspect/inspect-image.sh',
    ], { encoding: 'utf8', maxBuffer: 20_000_000 }).trim().split('\n').at(-1),
  );
  return summary;
}

const opts = { skip: image ? false : 'ORCHESTRATOR_IMAGE not set' };

test('both workflows are seeded, published, with every Schedule Trigger disabled', opts, () => {
  const { workflows } = inspect();
  assert.deepEqual(workflows.map((w) => w.id).sort(), ['elevDigest00001', 'elevIngest00001']);
  for (const wf of workflows) {
    assert.equal(wf.active, true, `${wf.id} is not published`);
    const schedules = wf.nodes.filter((n) => n.type === 'n8n-nodes-base.scheduleTrigger');
    assert.ok(schedules.length >= 1, `${wf.id} lost its schedule node`);
    for (const s of schedules) assert.equal(s.disabled, true, `${wf.id}: "${s.name}" would fire inside the Lambda`);
    const webhooks = wf.nodes.filter((n) => n.type === 'n8n-nodes-base.webhook' && !n.disabled);
    assert.equal(webhooks.length, 1, `${wf.id} needs exactly one enabled webhook`);
  }
});

test('every secret field of the seeded credentials is empty', opts, () => {
  const { credentials } = inspect();
  const byType = Object.fromEntries(credentials.map((c) => [c.type, c.data]));
  assert.equal(byType.httpHeaderAuth.value, '');
  assert.equal(byType.httpHeaderAuth.name, 'X-Ingest-Token');
  for (const field of ['accessKeyId', 'secretAccessKey', 'sessionToken']) {
    assert.equal(byType.aws[field] ?? '', '', `aws.${field} is not empty and would shadow the overwrite`);
  }
  assert.equal(byType.aws.temporaryCredentials, true, 'without it n8n drops the session token');
});

test('the image carries no secret and no encryption key setting', opts, () => {
  const { secretHits, env } = inspect();
  assert.deepEqual(secretHits, []);
  assert.equal(env.N8N_ENCRYPTION_KEY, null);
});

test('privacy and routing settings are baked in', opts, () => {
  const { env } = inspect();
  assert.equal(env.N8N_OTEL_TRACES_INCLUDE_NODE_SPANS, 'false');
  assert.equal(env.N8N_AGENTS_TRACING_RECORD_INPUTS, 'false');
  assert.equal(env.N8N_AGENTS_TRACING_RECORD_OUTPUTS, 'false');
  assert.equal(env.N8N_BLOCK_ENV_ACCESS_IN_NODE, 'false');
  assert.equal(env.ELEVATOR_API_BASE_URL, 'https://elevator.dsaavedra.dev');
});
