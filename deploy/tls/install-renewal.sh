#!/bin/sh
# Install the TLS renewal schedule onto the production instance.
#
# Run by .github/workflows/deploy.yml on every deploy, after the smoke check, so
# that host configuration is restored from the repository continuously instead of
# being typed once into an SSM session and then drifting from it unobserved. It is
# idempotent by design: running it is how drift is healed rather than documented.
#
# PREFIX, SYSTEMCTL and CRONTAB exist so backend/tests/unit/test_tls_renewal_config.py
# can execute this script — the real one, not a copy of its logic — against a
# throwaway filesystem with stubbed commands. Production passes none of them.
set -eu

here=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
: "${PREFIX:=}"
: "${SYSTEMCTL:=systemctl}"
: "${CRONTAB:=crontab}"

systemd_dir="${PREFIX}/etc/systemd/system"
hook_dir="${PREFIX}/etc/letsencrypt/renewal-hooks/deploy"
backup_dir="${PREFIX}/root"

# 1. The binary the unit names must be there. This is the check whose absence
#    cost ninety-three days: a unit pointing at a path that does not resolve is
#    precisely the configuration that was live, and it reported nothing.
#
#    The path is read out of the unit rather than repeated here, so there is one
#    source of truth and a certbot that moves cannot pass this check while the
#    unit still points at thin air.
certbot=$(sed -n 's/^ExecStart=\([^ ]*\).*/\1/p' "${here}/certbot-renew.service")
if [ -z "$certbot" ]; then
    echo "install-renewal: certbot-renew.service declares no ExecStart" >&2
    exit 1
fi
if [ ! -x "${PREFIX}${certbot}" ]; then
    echo "install-renewal: ${certbot} is missing or not executable — renewal cannot run" >&2
    echo "install-renewal: install certbot (pip3 install certbot certbot-dns-route53)," >&2
    echo "install-renewal: or correct ExecStart in deploy/tls/certbot-renew.service" >&2
    exit 1
fi

# 2. The files.
mkdir -p "$systemd_dir" "$hook_dir"
install -m 0644 "${here}/certbot-renew.service" "${systemd_dir}/certbot-renew.service"
install -m 0644 "${here}/certbot-renew.timer" "${systemd_dir}/certbot-renew.timer"
install -m 0755 "${here}/reload-nginx-deploy-hook.sh" "${hook_dir}/reload-nginx.sh"

# 3. The schedule.
"$SYSTEMCTL" daemon-reload
"$SYSTEMCTL" enable --now certbot-renew.timer

# 4. Prove the unit can actually renew, by running it. An executable at the end of
#    ExecStart is not the same claim: `ExecStart=/usr/local/bin/certbot renew
#    --quiet --dry-run` would satisfy every file-reading check ever written here
#    and renew nothing for as long as the instance lives, reporting success to
#    journald the whole time. So does a broken dns-route53 plugin, a revoked IAM
#    key, or certbot's Python being upgraded out from under it.
#
#    This is cheap: `certbot renew` exits 0 without contacting the ACME server
#    when nothing is within thirty days of expiry. When something is, this renews
#    it during a deploy, which is when someone is watching.
#
#    Under `set -e` a failure here stops the script *before* step 5 removes the
#    legacy crontab renewer. That ordering is deliberate: a host whose new
#    mechanism cannot run keeps the old one, even hand-patched, rather than being
#    left with neither.
"$SYSTEMCTL" start --wait certbot-renew.service
echo "install-renewal: certbot-renew.service ran from its own unit environment"

# 5. One renewer in root's crontab. Certbot's own lock file makes a collision
#    harmless, but
#    two mechanisms mean nobody can say which one is live — and the crontab one
#    is the one no deploy can reach.
#
#    The match is on `certbot`, not on the exact phrase `certbot renew`: the line
#    that expired the certificate would have survived a narrower match after any
#    reformatting (`certbot -q renew`, an absolute path, a wrapper script). This
#    only ever touches root's crontab — /etc/cron.d, /etc/crontab and other
#    users' crontabs are neither inspected nor claimed, which is why the spec
#    scenario says root's crontab and nothing more.
if current=$("$CRONTAB" -l 2>/dev/null); then
    if printf '%s\n' "$current" | grep -q 'certbot'; then
        mkdir -p "$backup_dir"
        # The PID is part of the name because a timestamp to the second is not
        # unique: two runs inside the same second would otherwise write to the
        # same path, and the second would overwrite the only copy of what the
        # first removed.
        backup="${backup_dir}/crontab.bak.$(date -u +%Y%m%dT%H%M%SZ).$$"
        printf '%s\n' "$current" > "$backup"
        # `|| true`: when the certbot line was the only entry, grep -v matches
        # nothing and would take the script down with it under `set -e`.
        filtered=$(printf '%s\n' "$current" | grep -v 'certbot' || true)
        printf '%s\n' "$filtered" | "$CRONTAB" -
        echo "install-renewal: removed the legacy crontab renewer (backup: ${backup})"
    fi
fi

# 6. What the deploy log should carry away: whether the last run succeeded, and
#    when the next one is. "Armed" and "working" are different questions, and the
#    outage happened because only the first was ever asked.
"$SYSTEMCTL" list-timers --all certbot-renew.timer || true
if "$SYSTEMCTL" is-failed --quiet certbot-renew.service; then
    echo "install-renewal: WARNING certbot-renew.service is in a failed state" >&2
    "$SYSTEMCTL" status --no-pager --lines=20 certbot-renew.service || true
    exit 1
fi
echo "install-renewal: ok"
