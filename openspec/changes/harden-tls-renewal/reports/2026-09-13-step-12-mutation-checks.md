# Step 12 Report — Mutation Checks

- Date: 2026-09-13
- Change: harden-tls-renewal
- Command: each mutation applied to the real file, `pytest
  tests/unit/test_tls_renewal_config.py` run, file restored, one at a time

## Results

| # | Mutation | Test that went red |
|---|---|---|
| 12.1 | `ExecStart=certbot renew` — the original bug | `test_renewal_unit_invokes_certbot_by_absolute_path` **+ 4 installer tests** |
| 12.2 | deploy hook without `exec -T` | `test_deploy_hook_reloads_nginx_without_requiring_a_tty` |
| 12.3 | timer fires once a day | `test_timer_checks_twice_a_day_and_catches_up_after_downtime` |
| 12.4 | installer keeps the legacy crontab renewer | `test_installer_removes_the_legacy_crontab_renewer_and_keeps_a_backup` |
| 12.5 | installer drops the missing-binary check | `test_installer_fails_when_the_binary_the_unit_names_is_missing` |
| 12.6 | expiry threshold 45 days (outside the renewal window) | `test_expiry_threshold_sits_inside_the_renewal_window` |
| 12.7 | expiry workflow not scheduled | `test_expiry_workflow_is_scheduled_and_can_be_run_on_demand` |
| 12.8 | apex host dropped from the expiry matrix | `test_expiry_workflow_is_scheduled_and_can_be_run_on_demand` |
| 12.9 | expiry check stops verifying the chain | `test_expiry_check_validates_the_chain_without_trust_overrides` |
| 12.10 | renewal installed **before** the smoke check | `test_deploy_workflow_installs_the_renewal_after_the_smoke_check` |

Suite restored to **13 passed** after every mutation.

## 12.1 reddens five tests, and that is correct

The installer reads the certbot path out of `certbot-renew.service` rather than
repeating it, so a bare `ExecStart` also makes the installer's executable check
fail — which is the single source of truth working as intended, not leakage. The
four installer tests going red alongside is the more faithful reproduction of the
incident: on 12 June the unit and the binary disagreed, and nothing anywhere
objected.

## Two guards did not guard, and were rewritten

**Mutation 12.2 passed on the first run.** Deleting `exec -T` from the hook's
actual command left all 13 tests green, because the assertion searched the whole
file and the *comment* above that command explains why `exec -T` matters. The
guard was satisfied by its own prose.

**The same defect sat in the hostname assertion.** It checked that
`"dsaavedra.dev"` appeared anywhere in the workflow file, and the header comment
mentions the certificate by name — so dropping the apex host from the matrix would
have passed too. It was never run in that state; it was found by looking for the
same shape after 12.2.

Both were rewritten to read what executes rather than what is written near it:

- a `_code()` helper strips comment lines, and the hook and expiry-script
  assertions run against that;
- the hostname assertion reads the parsed `strategy.matrix.host` list, and also
  requires `fail-fast: false` so one host cannot mask the other.

Mutations 12.2, 12.8 and 12.9 then reddened as they should. This is the whole
argument for running the mutation before trusting the guard: the version that
passed 13/13 contained a test that could never fail for the defect it was written
to catch — which is a smaller copy of what this entire change is about.

## 12.10 was a bad mutation before it was a passing one

The first attempt inserted a placeholder step instead of reordering, so the smoke
step kept its position and nothing should have gone red. Re-done by swapping the
two step blocks outright, the ordering guard failed as expected. Recorded because
"no test went red" means either a weak guard or a weak mutation, and telling them
apart is the work.

## Outcome

PASS — 10 mutations, 10 reddened the intended guard, 2 guards repaired in the
process.
