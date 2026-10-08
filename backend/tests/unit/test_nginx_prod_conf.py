"""The production proxy rate-limits the ingest and inference endpoints.

The token decides who may write; this bounds how fast anyone can hit the routes
that write to the database and start inference runs on a t3.micro — including a
holder of a leaked token, or a client probing for one. Rejected at the proxy,
those requests never cost the backend a database session.

Parsed statically: the suite cannot run nginx, and `nginx -t` against the real
file is part of the change's endpoint verification. What can rot silently here
is the *shape* — a limit moved onto the generic `/api/` block throttles the
dashboard, a limit dropped from one location leaves it open — and that is what
these tests pin.
"""

import pathlib
import re

import pytest

PROD_CONF = pathlib.Path(__file__).parents[3] / "nginx" / "prod.conf"
LIMITED_PATHS = ["/api/telemetry/readings", "/api/inference/run"]
ZONE = "elevator_ingest"


def _conf() -> str:
    # Comments stripped so a commented-out directive cannot satisfy a test.
    return re.sub(r"#[^\n]*", "", PROD_CONF.read_text())


def _block_body(conf: str, opener: str, start_at: int = 0) -> str:
    """Body of the first block whose opening matches the regex ``opener``."""
    match = re.compile(opener).search(conf, start_at)
    assert match, f"no block matching {opener!r} in nginx/prod.conf"
    depth, start = 1, match.end()
    for i in range(start, len(conf)):
        if conf[i] == "{":
            depth += 1
        elif conf[i] == "}":
            depth -= 1
            if depth == 0:
                return conf[start:i]
    raise AssertionError(f"unbalanced braces after {opener!r}")


def _location_body(conf: str, header: str) -> str:
    return _block_body(conf, r"location\s+" + re.escape(header) + r"\s*\{")


def _server_bodies(conf: str) -> list[str]:
    bodies, at = [], 0
    while (match := re.search(r"\bserver\s*\{", conf[at:])) is not None:
        body = _block_body(conf, r"\bserver\s*\{", at)
        bodies.append(body)
        at += match.end() + len(body)
    return bodies


def test_the_rate_limit_zone_is_declared_at_the_designed_rate():
    """Prefixed with the app's name: this nginx is shared with the portfolio.

    The value is pinned, not just the shape: `rate=100000r/s` would keep every
    other test here green while limiting nothing.
    """
    assert re.search(
        r"limit_req_zone\s+\$binary_remote_addr\s+zone=" + ZONE + r":1m\s+rate=12r/m\s*;",
        _conf(),
    )


def test_rate_limiting_is_enforced_rather_than_dry_run():
    """`limit_req_dry_run on` logs would-be rejections and rejects nothing."""
    assert "limit_req_dry_run" not in _conf()


@pytest.mark.parametrize("path", LIMITED_PATHS)
def test_each_limited_endpoint_has_an_exact_match_location_with_the_limit(path: str):
    body = _location_body(_conf(), "= " + path)

    assert re.search(r"limit_req\s+zone=" + ZONE + r"\s+burst=10\s+nodelay\s*;", body), body
    assert re.search(r"limit_req_status\s+429\s*;", body), body
    # Still proxied, or the limit would be the least of the problems.
    assert re.search(r"proxy_pass\s+http://backend:8000\s*;", body), body


def test_the_generic_api_location_is_not_limited():
    """The dashboard's reads go through here and must never see a 429."""
    body = _location_body(_conf(), "/api/")

    assert "limit_req" not in body


@pytest.mark.parametrize("header", ["= " + path for path in LIMITED_PATHS] + ["/api/"])
def test_api_redirects_are_rewritten_to_https(header: str):
    """The backend speaks plain HTTP behind the proxy, so its trailing-slash
    redirect says `http://` — and a client that re-sends `X-Ingest-Token` on
    redirect would put it on the cleartext port. A trailing-slash path falls
    through to the generic `/api/` block, so that one needs the rewrite too.
    """
    body = _location_body(_conf(), header)

    assert re.search(r"proxy_redirect\s+http://\s+https://\s*;", body), body


def test_the_cleartext_server_only_redirects():
    """Anything proxied on port 80 would carry the token in clear."""
    port_80 = [b for b in _server_bodies(_conf()) if re.search(r"listen\s+80\s*;", b)]
    assert len(port_80) == 1, "expected exactly one port-80 server block"

    directives = {
        line.strip().split()[0]
        for line in port_80[0].splitlines()
        if line.strip()
    }
    assert directives == {"listen", "server_name", "return"}, directives
    assert re.search(r"return\s+301\s+https://", port_80[0])
