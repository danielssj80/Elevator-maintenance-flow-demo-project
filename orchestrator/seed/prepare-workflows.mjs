// Build-time only: turn the repository's workflow definitions into the ones
// seeded into the Lambda image.
//
// 1. Every Schedule Trigger is DISABLED. EventBridge decides when work runs; a
//    schedule that fell inside an invocation's ~20 s lifetime would start a
//    second, unrequested execution (spec: "only the webhook triggers").
// 2. Credentials are attached by id to the placeholders in credentials.json,
//    the same mapping scripts/n8n-import-workflow.sh applies locally.
//
// Usage: node prepare-workflows.mjs <in-dir> <out-dir>
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const [inDir, outDir] = process.argv.slice(2);

const CREDENTIALS = {
  'n8n-nodes-base.httpRequest': ['httpHeaderAuth', 'elevatorIngest01', 'Elevator ingest token'],
  '@n8n/n8n-nodes-langchain.lmChatAwsBedrock': ['aws', 'elevatorBedrock01', 'Elevator Bedrock'],
};

mkdirSync(outDir, { recursive: true });
for (const file of readdirSync(inDir).filter((f) => f.endsWith('.json'))) {
  const wf = JSON.parse(readFileSync(join(inDir, file), 'utf8'));
  for (const node of wf.nodes) {
    if (node.type === 'n8n-nodes-base.scheduleTrigger') node.disabled = true;
    const mapping = CREDENTIALS[node.type];
    if (!mapping) continue;
    const [kind, id, name] = mapping;
    if (kind === 'httpHeaderAuth' && node.parameters?.genericAuthType !== 'httpHeaderAuth') continue;
    node.credentials = { [kind]: { id, name } };
  }
  writeFileSync(join(outDir, file), JSON.stringify(wf));
  console.log(`${wf.id} ${file}`);
}
