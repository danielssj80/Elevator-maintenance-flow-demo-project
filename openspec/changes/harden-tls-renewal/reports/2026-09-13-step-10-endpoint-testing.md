# Step 10 Report — Endpoint Testing

- Date: 2026-09-13
- Change: harden-tls-renewal
- Target: **production**, with a verifying client. No endpoint changed in this
  change; the production HTTPS surface is its subject, and `localhost` cannot
  demonstrate a certificate. No mutating request was issued, so no database state
  needed restoring.

## Endpoints tested

### GET https://elevator.dsaavedra.dev/health
```
$ curl -s -w " [%{http_code}]" https://elevator.dsaavedra.dev/health
{"status":"ok"} [200]
```
No `-k`. Three days ago this same command returned nothing with curl exit 60.

### GET https://elevator.dsaavedra.dev/api/elevators
```
100 elevators; first: ELV-073 0.9981
```
200, one hundred rows, sorted by risk score descending — the top row is 0.9981.

### GET https://dsaavedra.dev/ (the co-located portfolio)
```
200
```
The other site on the same nginx and the same certificate. It went down with the
Elevator and comes back with it; checking it here is the point.

### GET http://elevator.dsaavedra.dev/
```
301 https://elevator.dsaavedra.dev/
```

## Served certificates

```
elevator.dsaavedra.dev: issuer=C=US, O=Let's Encrypt, CN=YE2
                        notBefore=Sep 13 16:52:29 2026  notAfter=Dec 12 16:52:28 2026
                        SAN: DNS:*.dsaavedra.dev, DNS:dsaavedra.dev
dsaavedra.dev:          identical (one wildcard certificate, one nginx)
```

## The new check, against production

```
$ sh scripts/check-tls-expiry.sh elevator.dsaavedra.dev
check-tls-expiry: elevator.dsaavedra.dev: expires Dec 12 16:52:28 2026 GMT (89 days remaining)
$ sh scripts/check-tls-expiry.sh dsaavedra.dev
check-tls-expiry: dsaavedra.dev: expires Dec 12 16:52:28 2026 GMT (89 days remaining)
```

Both exit 0 at 89 days against a 21-day threshold. Its failure path is proven
separately and behaviourally: `test_expiry_check_fails_when_no_certificate_can_be_read`
runs the script against an unresolvable host and requires a non-zero exit, so the
check cannot pass for want of a date to compare.

## Error cases

- Unreachable host → non-zero exit, message naming the host (unit test, above).
- Untrusted chain → non-zero exit, asserted structurally by
  `test_expiry_check_validates_the_chain_without_trust_overrides` and proven by
  mutation 12.9, which added a verification-disabling flag and reddened it.
- 404/422 endpoint error cases: not applicable — no endpoint is added or altered
  by this change.

## Outcome

PASS
