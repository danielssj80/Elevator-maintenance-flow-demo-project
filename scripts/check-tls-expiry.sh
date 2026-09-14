#!/bin/sh
# Fail if the certificate a host actually SERVES is close to expiry.
#
# Usage: scripts/check-tls-expiry.sh <host[:port]> [min_days]
#
# Requires GNU date (`date -u -d`), so it runs on the Linux instance and on the
# ubuntu-latest runners; on macOS use `gdate` from coreutils.
#
# Run daily by .github/workflows/tls-expiry-check.yml and on every deploy by
# deploy.yml. Deliberately not run on the instance: a checker that lives on the
# host cannot report that the host is unreachable.
#
# On 2026-09-10 the *.dsaavedra.dev certificate expired after ninety-three days
# without a renewal and nothing in this system noticed for three more days. This
# is the thing that notices.
set -eu

host="${1:?usage: check-tls-expiry.sh <host[:port]> [min_days]}"
# host[:port] exists so the failure paths can be exercised against a local TLS
# server in the test suite instead of against production.
case "$host" in
    *:*) authority="$host"; sni="${host%%:*}" ;;
    *)   authority="${host}:443"; sni="$host" ;;
esac
# 21 days. Renewal begins at 30 days remaining, so fewer than 21 means the renewal
# mechanism is broken rather than merely due. A threshold that fires while renewal
# is still expected to happen teaches its reader to ignore it.
min_days="${2:-21}"

# The certificate the server presents, not the file on disk. On 2026-09-13 those
# were the same expired certificate, but the other failure mode — renewed on disk,
# stale in nginx's memory because a reload failed — is invisible to a file check
# and just as fatal to every client.
# `timeout` is not decoration. openssl s_client has no handshake timeout of its
# own: a host that completes the TCP connection and then says nothing blocks
# forever. In the deploy workflow that would stall a job whose concurrency group
# is `production-deploy` with cancel-in-progress disabled, so every subsequent
# production deploy would queue behind a check that never returns -- a silent
# failure of exactly the kind this script exists to catch.
end=$(echo | timeout 15 openssl s_client -connect "$authority" -servername "$sni" 2>/dev/null \
    | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2 || true)

if [ -z "$end" ]; then
    echo "check-tls-expiry: ${host}: could not read a certificate — host unreachable or TLS handshake failed" >&2
    exit 1
fi

end_epoch=$(date -u -d "$end" +%s)
days=$(( (end_epoch - $(date -u +%s)) / 86400 ))
echo "check-tls-expiry: ${host}: expires ${end} (${days} days remaining)"

if [ "$days" -lt "$min_days" ]; then
    echo "check-tls-expiry: ${host}: only ${days} days remaining, below the ${min_days}-day threshold" >&2
    echo "check-tls-expiry: renewal should already have run — check 'systemctl list-timers certbot-renew.timer'" >&2
    echo "check-tls-expiry: and 'journalctl -u certbot-renew' on the instance" >&2
    exit 1
fi

# Dates are not the only way TLS breaks. An incomplete chain, a name mismatch or a
# revoked intermediate fails a real client while the dates read perfectly here, so
# the check includes one request from a client that verifies. Never pass a flag
# that disables verification: every other health check in this system was blind to
# the outage precisely because none of them verified anything.
if ! curl -sS --max-time 15 -o /dev/null "https://${authority}/"; then
    echo "check-tls-expiry: ${host}: a verifying client could not complete the request" >&2
    exit 1
fi
