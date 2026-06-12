# Step 12 — E2E Testing (Playwright)

**Date:** 2026-06-12
**Change:** migrate-backend-postgresql

## Results

| Step | Check | Result |
|------|-------|--------|
| 12.2 | Dashboard renders: "Elevator Maintenance" header, 100 rows in table, stats (3 high, 6 medium, 37 out-of-scope), sorted by risk desc | PASS |
| 12.3 | ELV-001 detail: model explanation visible, 3 prediction drivers, trend sparkline, "Submit post-visit report" link | PASS |
| 12.4 | Report form submitted (technician "E2E Test Technician"); success redirect to detail page; row id=3 confirmed in `visit_reports` | PASS |
| 12.5 | DB restored — all `visit_reports` rows deleted | PASS |

## Notes

- The `201 Created` response is transparent to the UI: `PostVisitReport.tsx` does not inspect the status code, so the 200→201 change has zero UI impact.
- `ref=eN` selectors from the Playwright MCP snapshot do not work in `browser_click`; CSS/text selectors (`button:has-text(...)`, `input[placeholder=...]`) work correctly.
- The 2-second `setTimeout` redirect after form submit means the "Report submitted" success screen flashed before Playwright could snapshot it — the final snapshot shows the detail page, which confirms the full happy path completed.
