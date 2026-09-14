# TLS renewal — host configuration

Everything in this directory configures the **production host**, not a container.
It is installed onto the EC2 instance by `install-renewal.sh`, which
`.github/workflows/deploy.yml` runs on every deploy.

| File | Installed to | Purpose |
|---|---|---|
| `certbot-renew.service` | `/etc/systemd/system/` | Runs `certbot renew` by absolute path |
| `certbot-renew.timer` | `/etc/systemd/system/` | Twice daily, jittered, catches up after downtime |
| `reload-nginx-deploy-hook.sh` | `/etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh` | Reloads nginx after a successful renewal |
| `install-renewal.sh` | — | Installs the three above, enables the timer, removes the legacy crontab renewer |

**Do not edit these files on the instance.** The next deploy overwrites them from
the repository, which is the entire point: the mechanism this replaced was a
crontab line that existed only on the host, drifted from what the documentation
claimed, and failed silently for ninety-three days until the certificate expired
and took both sites down.

## Verifying it

Never in an interactive shell alone — that is how the previous mechanism was
certified while it had never once worked. Check it the way it actually runs:

```bash
systemctl list-timers --all certbot-renew.timer      # armed? when next?
sudo journalctl -u certbot-renew -n 50               # did it run, and what did it return?
sudo systemctl start certbot-renew.service           # run it now, from the unit's own environment
sudo /usr/local/bin/certbot renew --dry-run --run-deploy-hooks
```

`sudo` matters on the journal line: without it the SSM user sees `-- No entries --`
for a unit that ran fine. And `LAST`/`PASSED` of `-` in `list-timers` only means the
timer itself has not fired yet — a manual `systemctl start` does not set them.

`--run-deploy-hooks` is not optional in that last command: a plain `--dry-run`
does not execute deploy hooks, so it proves nothing about the reload. That default
is half of why the original verification certified a broken mechanism.

Detection lives off the host, in `.github/workflows/tls-expiry-check.yml` and
`scripts/check-tls-expiry.sh`.
