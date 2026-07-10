# Adversarial review — motor-life-feature

- Date: 2026-07-10
- Change: motor-life-feature (merged to `main` via PR #18, deployed to production)
- Reviewer stance: independent adversarial pass before archive

## Scope reviewed

- Artifacts: `proposal.md`, `design.md`, `tasks.md`
- Implementation: `backend/ml/generate_predictions.py`, regenerated `backend/ml/predictions.json`,
  migration `2c43876e02dd_resync_motor_life_feature.py`, `docs/data-model.md`
- Consumers checked for the empty-array / new-feature cases: `backend/app/seed.py`,
  `services/elevator_service.py`, `services/briefing_service.py`, `frontend/FeatureBar.tsx`

## Verifications run

- `ruff check` on changed Python: **clean**.
- `generate_predictions.py` reproducible across two runs: **identical output**.
- Acceptance on committed `predictions.json`: 100 entries; 70 in-scope each with 3 features
  (impacts sum 0.99–1.01) and 6-point trend; **5 high / 5 medium / 60 low**; ≥1 high; medium
  tier populated; no legacy `"N hrs"` strings; motor-life feature present.
- Migration dry-run (sqlite, simulating stale prod rows): 100 rows updated in place by PK,
  210 features, `visit_reports` preserved, new `% remaining` values applied.
- Fresh-vs-existing DB paths reasoned: fresh → `seed_database()` seeds (migrations no-op on
  empty table); existing → migration resyncs, seed skips (`count > 0`). No double-seed.
- Production (post-deploy, user-confirmed): 5 high / 5 medium visible.

## Findings

| Severity | Finding | Resolution |
|---|---|---|
| Minor | Out-of-scope entries in `predictions.json` carried `trend: [0,0,0,0,0,0]` while `seed.py` and the migration both map `None → trend: []` (the served DB/API value). Latent inconsistency, no runtime impact, but contradicts this change's own acceptance wording. | **Fixed**: `generate_predictions.py` now writes `trend: []` for out-of-scope; `predictions.json` regenerated. Aligns the artifact with production (DB already served `[]`), no redeploy needed. |
| Minor | No delta spec for the named `elevator-explainability` capability. | Accepted — consistent with `ml-offline-training` precedent; `docs/data-model.md` carries the feature-framing contract. |
| Nit | `high_count` is printed before the medium-guarantee step (never re-printed). | Cosmetic log only; left as-is. |

## Verdict

**PASS (adversarial).** No blockers or majors. Core logic (motor-life mapping, age-independent
external factors, medium-risk guarantee, in-place PK-preserving migration) is sound,
reproducible, lint-clean, and production-verified. The one substantive minor finding was fixed
in this archive commit. Archiving is advisable.
