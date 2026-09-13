# Incident Report — Expired TLS certificate, both sites

- Date: 2026-09-13
- Change: harden-tls-renewal
- Impact: `https://elevator.dsaavedra.dev` and `https://dsaavedra.dev` failed TLS
  verification for every client. The application itself never stopped serving.
- Certificate expired: 2026-09-10 11:29:08 UTC
- Detected: 2026-09-13, by a human opening the site
- Recovered: 2026-09-13 16:52 UTC

## What clients saw

```
$ curl -s -o /dev/null -w "%{http_code}\n" https://elevator.dsaavedra.dev/health
000                       # curl exit 60 — certificate verification failed
$ curl -sk https://elevator.dsaavedra.dev/health
{"status":"ok"}           # the stack was healthy the whole time
$ curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" http://elevator.dsaavedra.dev/
301 https://elevator.dsaavedra.dev/
```

One certificate and one nginx container serve both sites (`docs/deployment.md`,
*Co-located sites*), so a single expiry took down the demo and the personal
portfolio together.

## Evidence

**1. The certificate being served was the original one.**

```
subject=CN=dsaavedra.dev
issuer=C=US, O=Let's Encrypt, CN=YE2
notBefore=Jun 12 11:29:09 2026 GMT
notAfter =Sep 10 11:29:08 2026 GMT
SAN: *.dsaavedra.dev, dsaavedra.dev
```

`notBefore` is the afternoon of the `deploy-aws-https` deployment. The step 10
report of that change recorded the same expiry date on the day it was issued.

**2. The certificate on disk was the same original.** This is what separates
"never renewed" from "renewed but never reloaded":

```
$ sudo openssl x509 -noout -dates -in /etc/letsencrypt/live/dsaavedra.dev/cert.pem
notBefore=Jun 12 11:29:09 2026 GMT
notAfter=Sep 10 11:29:08 2026 GMT
```

**3. Certbot had not run since June.** The last entry in
`/var/log/letsencrypt/letsencrypt.log` is dated `2026-06-19 18:10` with
`Arguments: []` — a `certbot certificates` typed by hand a week after the
deployment. Ninety days of nightly renewal attempts left no entry at all, because
none of them reached certbot.

**4. The cause, reproduced in cron's environment.**

```
$ sudo env PATH=/usr/bin:/bin certbot --version
env: 'certbot': No such file or directory
```

`cronie` runs jobs with `PATH=/usr/bin:/bin`. `deploy-aws-https` installed certbot
with `pip3 install certbot certbot-dns-route53`, so the binary is at
`/usr/local/bin/certbot` — the same log confirms it: `Location of certbot entry
point: /usr/local/bin/certbot`. The crontab line began with a bare `certbot`, so
every run exited 127 on its first word and the `&&` discarded the rest.

**5. Nothing could report the failure.** `--quiet` suppressed output, AL2023 ships
no MTA so cron's mail to root was discarded, and AL2023 keeps no `/var/log/cron`
(`grep: /var/log/cron: No such file or directory`) because cronie logs to
journald. The renewal window opened on 2026-08-11 and produced 30 silent failures.

## Why the specification did not prevent it

**The scenario was right and its verification was not.** `production-deployment`
S7: *"Given the Let's Encrypt certificate is within 30 days of expiry, when the
certbot renewal cron job runs, then `certbot renew` completes successfully and
nginx reloads with the renewed certificate."* Task 10.6 of `deploy-aws-https`
closed it with `certbot renew --dry-run`, executed in the operator's interactive
SSM shell. That command:

- inherits the operator's `PATH`, so it cannot detect the defect that broke every
  scheduled run;
- does not run deploy hooks at all unless `--run-deploy-hooks` is passed, so it
  says nothing about the reload clause either.

Both clauses of the requirement went unverified while the task that owned them was
marked `[x]`.

**The capability was also unmachine-checkable.** `production-deployment` is the
only spec in the repository that `openspec validate` rejects — it is still in the
legacy `S1…S9` prose format with no `## Requirements` section:

```
$ openspec validate --specs
✗ spec/production-deployment
Totals: 10 passed, 1 failed (11 items)
```

**And the one check that would have caught it runs too rarely.** `deploy.yml`'s
smoke step uses `curl -sf`, which fails on an expired certificate. It runs only on
a merge to `main`. The last deploy before the outage was 2026-08-31 (`d79845a`),
ten days before expiry; nothing ran inside the window. Monitoring was explicitly
out of scope in the original change.

## Drift found while investigating

The live crontab line had acquired `exec -T`:

```
0 3 * * * certbot renew --quiet && docker compose -f /opt/elevator/docker-compose.prod.yml exec -T nginx nginx -s reload
```

`docs/deployment.md:204` and `deploy-aws-https/design.md:235` both document it
without `-T`. Nobody can say when or why the host diverged, which is the argument
for this change: unversioned host state cannot be reviewed, tested, or rebuilt.

Note that the `-T` mattered. Had the `PATH` defect not existed, the version in the
repository would have failed at the second command instead of the first —
`docker compose exec` without `-T` has no TTY under cron — and nginx would have
served a stale certificate from memory while the file on disk was current. Two
independent defects, both in one line, either of which produces an outage.

## Recovery

```
$ sudo /usr/local/bin/certbot renew
$ sudo docker compose -f /opt/elevator/docker-compose.prod.yml exec -T nginx nginx -s reload
```

Verified externally after the reload:

```
notBefore=Sep 13 16:52:29 2026 GMT
notAfter =Dec 12 16:52:28 2026 GMT
elevator.dsaavedra.dev/health → 200   (verifying client, no -k)
dsaavedra.dev/                → 200   (verifying client, no -k)
```

The crontab line was also given an absolute path, and a dry run under cron's own
environment now passes:

```
$ sudo env -i PATH=/usr/bin:/bin /usr/local/bin/certbot renew --dry-run --deploy-hook "..."
Congratulations, all simulated renewals succeeded
```

That is a patch on host state that no deploy re-asserts and no test can see. The
change this report belongs to is the durable fix.

## Follow-ups recorded, not fixed here

- certbot 4.2.0 runs on Python 3.9. boto3 ended Python 3.9 support in April 2026
  and certbot warns it is dropping it next release: *"Python 3.9 support will be
  dropped in the next planned release of Certbot"*. An upgrade of either breaks
  renewal again.
- The renewal credentials are long-lived IAM access keys in
  `/root/.aws/credentials`; nothing rotates them. `design.md` §6 records why they
  are not moved to the instance role in this change.
- No monitor exists that is independent of GitHub Actions scheduling.
