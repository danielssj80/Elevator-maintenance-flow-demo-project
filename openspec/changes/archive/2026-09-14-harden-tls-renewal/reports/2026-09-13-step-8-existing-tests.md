# Step 8 Report — Review of Existing Tests

- Date: 2026-09-13
- Change: harden-tls-renewal

## Nothing is invalidated by removing the crontab renewer

```
$ grep -rn -i "crontab\|certbot\|letsencrypt\|renew\|tls" backend/tests/ e2e/ \
    | grep -v test_tls_renewal_config.py
(no matches)
```

No test anywhere asserted the mechanism that has just been replaced. That is the
finding, not the absence of work: the renewal was verified once, by hand, in a
shell, and never again by anything. The certificate expired in the gap.

## Overlap with `test_dev_compose.py`

`backend/tests/unit/test_dev_compose.py` is the precedent this change follows —
the only other tests in the suite that read deployment configuration rather than
application code, written after a production gate was found open in the one
environment it existed to protect. Its eleven tests assert properties of
`docker-compose.yml` and `docker-compose.prod.yml`: the ingest token, the
production environment declaration, the absent orchestrator, the queue profile,
the OTel block.

No overlap and no contradiction with the new file, which asserts systemd units,
a shell hook, an installer and two workflows. Both share the same premise, and
`test_tls_renewal_config.py`'s docstring says so explicitly: a guard proven in a
fixture is not proven.

One property was **borrowed** from it and strengthened: `test_dev_compose.py`
reads its files and asserts on parsed structures; the new file does the same, and
where it must match text it strips comment lines first — after a mutation run
proved an assertion could be satisfied by the comment explaining it.

## Outcome

No existing test required updating.
