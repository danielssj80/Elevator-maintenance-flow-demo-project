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

# 4. Exactly one renewer. Certbot's own lock file makes a collision harmless, but
#    two mechanisms mean nobody can say which one is live — and the crontab one
#    is the one no deploy can reach.
if current=$("$CRONTAB" -l 2>/dev/null); then
    if printf '%s\n' "$current" | grep -q 'certbot renew'; then
        mkdir -p "$backup_dir"
        backup="${backup_dir}/crontab.bak.$(date -u +%Y%m%dT%H%M%SZ)"
        printf '%s\n' "$current" > "$backup"
        # `|| true`: when the certbot line was the only entry, grep -v matches
        # nothing and would take the script down with it under `set -e`.
        filtered=$(printf '%s\n' "$current" | grep -v 'certbot renew' || true)
        printf '%s\n' "$filtered" | "$CRONTAB" -
        echo "install-renewal: removed the legacy crontab renewer (backup: ${backup})"
    fi
fi

# 5. What the deploy log should carry away: when this will next actually run.
"$SYSTEMCTL" list-timers --all certbot-renew.timer || true
echo "install-renewal: ok"
