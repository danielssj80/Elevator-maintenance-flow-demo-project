# Step 14 Report — Independent Adversarial Review

- Date: 2026-10-08
- Change: serverless-n8n-orchestration
- Reviewer: cold-start agent in an isolated worktree, given only the branch, the base commit (`aaa0a61`), the skill and how to run the suites
- Reviewed: `aaa0a61...f6f2f02` (66 files)

## Verdict (first round)
**FAIL**: 6 Major findings, 8 Minor, 2 Questions. No security Blocker: no secret is committed, baked into an image or passed as a command parameter, and IAM is narrowly scoped.

## Findings and resolution

| # | Sev. | Finding | Resolution | Evidence after fix |
|---|---|---|---|---|
| 1 | Major | `shellcheck deploy/aws/*.sh` fails from the repo root (SC1091), so the CI `orchestrator` job would be red. The step 10 report's "clean" came from running inside `deploy/aws/` | `deploy/aws/.shellcheckrc` (`source-path=SCRIPTDIR`); CI runs `shellcheck -x deploy/aws/*.sh`; step 10 report corrected | koalaman/shellcheck v0.10.0 from the repo root: clean |
| 2 | Major | Plain `docker build` on Docker 29 (containerd store) produces an OCI **index** with attestations, which Lambda rejects | `--provenance=false --sbom=false` in `lambda-images.yml` and `40-lambda.sh`; new test asserts all 4 builds | Descriptor without flags: `vnd.oci.image.index.v1+json`; with flags: `vnd.oci.image.manifest.v1+json`. Mutation (drop the flags) → 1 failed |
| 3 | Major | Scheduler invokes asynchronously, so Lambda's default async retries (2 attempts, 6 h) still apply; spec says no retries | `40-lambda.sh`: `put-function-event-invoke-config --maximum-retry-attempts 0 --maximum-event-age-in-seconds 900`; spec scenario added | dry run prints the call |
| 4 | Major | Lambda transport: `Payload.read()` and `json.loads` sat outside the `try`. A stream reset or read timeout → 500; malformed answers → 500 | Read inside the `try` (→ 503); decode and shape checked (→ 502); `_call` helper | 9 new tests; mutations: read outside try → 13 failed; shape unchecked → 2; keys unchecked → 1 |
| 5 | Major | Rollout plan required production checks before the merge that only the merged backend can pass | Migration plan reordered: provision → pre-merge checks `main` supports → merge (schedules disabled) → post-merge checks → enable. design.md, tasks 11/15, `docs/deployment.md` | — |
| 6 | Major | Spec "no alarm satisfiable by missing data" vs error alarms `notBreaching`; nothing alarmed on ingest going silent | `elevator-ingest-missing` (2 × 1 h, breaching). Spec states the split explicitly: silence alarms breach, error alarms do not. Silence alarms notify only while the schedules are enabled (`50-schedules.sh` toggles their actions) | dry run of `50 --enable` prints `enable-alarm-actions` |
| 7 | Minor | Policy test missed a scoped wildcard (`parameter/elevator/orchestrator/*`) | Any `*` in a resource rejected except `log-group:<name>:*`; exact resource sets pinned per policy | Reviewer's surviving mutation now → 2 failed |
| 8 | Minor | `retries={"max_attempts": 1}` means 2 attempts | `{"total_max_attempts": 1}`; test asserts it | — |
| 9 | Minor | `30-ssm.sh` treated any `get-parameter` failure as "absent" and overwrote the token | Create with `Overwrite: false`; only `ParameterAlreadyExists` counts as kept; any other error stops the script | — |
| 10 | Minor | `70-host-env.sh` exited 0 on a failed Run Command; `export IMAGE_TAG=$(…)` hid a git failure | Exits non-zero unless `Success`; tag assigned before export | — |
| 11 | Minor | `function-updated-v2` after create; misleading concurrency message | `function-active-v2` after create; AWS error shown | — |
| 12 | Minor | No deadline from `Lambda-Runtime-Deadline-Ms`; `spansFlushed` forced-true mutation survived | Bootstrap passes the deadline; readiness and the webhook (`AbortSignal`) end 25 s before it; 3 new tests | Mutations: readiness ignores budget → 1; webhook unbounded → 1; `spansFlushed: true` → 1 |
| 13 | Minor | `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` let any expression read the token, the OTLP header and the AWS session | `$env` stays blocked everywhere; the image build rewrites the backend address into the HTTP nodes (`prepare-workflows.mjs`, which fails on an unexpected URL or a non-origin argument). Spec requirement rewritten | Local stack and RIE re-run with `$env` blocked: 70 readings, execution id = invocation id; image tests assert URLs and the block (26 passed) |
| 14 | Minor | Silence alarm would email from provisioning until cutover; warm sandboxes keep a rotated token | Covered by #6; rotation note already in `docs/deployment.md` | — |
| Q1 | Question | Is 26 × 1 h evaluation (93,600 s) accepted? | Verified at provisioning (task 11.2); fallback 13 × 2 h documented in D9 | open until 11.2 |
| Q2 | Question | Does the deploy role need ECR repository-policy permissions for `UpdateFunctionCode`? | The repository policy Lambda needs is set when the admin creates the function; checked at 15.2 | open until 15.2 |

## Evidence after the fixes
- Backend suite (Python 3.12, postgres:16-alpine): **365 passed**; `ruff check`: clean
- Orchestrator: 21 passed + 5 skipped without an image; **26 passed** with the production image (`vnd.oci.image.manifest.v1+json`)
- Scorer tests in the Lambda image: 23 passed
- shellcheck from the repository root: clean
- RIE end to end against the local stack (image built for the local origin): ingest 24.6 s, 70 accepted, `spansFlushed: true`; daily run 22.3 s (digest degraded on the stub's fake AWS keys, as before); EMF lines emitted for both
- `openspec validate --strict`: valid
- Dry run: `reports/2026-10-08-aws-dry-run.txt` (41 calls)

## Outcome
All Major and Minor findings fixed or covered by spec. Two questions remain, verifiable only against AWS (11.2, 15.2).
