# Step 9 — Blocker fix verification (SHA pinning + build concurrency)

**Date:** 2026-10-07
**Scope:** tasks 1.6, 3.5, 9.5, 9.6 — verified after the fact, at archive time, against
the most recent production deploy rather than a dedicated push.

## 9.5 — actionlint (covers 1.6 and 3.5)

The original blocker was the sandbox: no Docker daemon and no network to fetch the
binary. Run instead from a throwaway venv with `actionlint-py`, which ships the
upstream release binary:

```
$ actionlint --version
1.7.12
$ actionlint .github/workflows/build-images.yml .github/workflows/deploy.yml
$ echo $?
0
```

Exit 0, no findings, on the workflows as they stand on `main` (`a4ac001`) — which
include the step-9 `concurrency` group and the `IMAGE_TAG` export.

## 9.6 — End-to-end on a real push to `main`

The SHA-pinning fix shipped in #28 (`97034ac`). Every deploy since has run with it;
the evidence below is the latest one, for commit `a4ac001` (#35), on 2026-09-14.

| Check | Evidence |
|---|---|
| Build succeeds with the `concurrency` block | Run `34816789639` "Build and push images", head `a4ac0012…`, conclusion `success` (07:12:38–07:14:46Z). `build-images.yml` carries `concurrency: group: build-images, cancel-in-progress: false`. |
| Deploy triggered by the build | Run `34816961434` "Deploy to production", event `workflow_run`, conclusion `success`. |
| Pulled tag is the commit SHA, not `latest` | SSM command exports `IMAGE_TAG=a4ac0012b15667c0502429b17c7bcf622e061db5`; log shows `Image ghcr.io/danielssj80/elevator-backend:a4ac0012… Pulled` and `Image ghcr.io/danielssj80/elevator-frontend:a4ac0012… Pulled`. No `:latest` pull for either app image. |
| No build on the host | No `Building` / `Step N/M` output in the deploy log. |
| Smoke check passes with no outage | `SSM command status: Success` then `Health check passed on attempt 1` (07:15:30Z); `elevator-backend-1 Healthy`. |

The five deploys before it (runs `33654577843`, `33407753064`, `33364394223`,
`33305641296`, `29819578613`) also concluded `success`.

## Result

Tasks 1.6, 3.5, 9.5, 9.6 and 9.7 complete. The change is ready to archive; its delta
spec was already synced into `openspec/specs/deploy-pipeline/spec.md` in task 9.4.
