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


def _location_body(conf: str, header: str) -> str:
    """Body of the first `location <header> { ... }`, braces balanced."""
    match = re.search(r"location\s+" + re.escape(header) + r"\s*\{", conf)
    assert match, f"no `location {header}` block in nginx/prod.conf"
    depth, start = 1, match.end()
    for i in range(start, len(conf)):
        if conf[i] == "{":
            depth += 1
        elif conf[i] == "}":
            depth -= 1
            if depth == 0:
                return conf[start:i]
    raise AssertionError(f"unbalanced braces after `location {header}`")


def test_the_rate_limit_zone_is_declared():
    """Prefixed with the app's name: this nginx is shared with the portfolio."""
    assert re.search(
        r"limit_req_zone\s+\$binary_remote_addr\s+zone=" + ZONE + r":\S+\s+rate=\S+;",
        _conf(),
    )


@pytest.mark.parametrize("path", LIMITED_PATHS)
def test_each_limited_endpoint_has_an_exact_match_location_with_the_limit(path: str):
    body = _location_body(_conf(), "= " + path)

    assert re.search(r"limit_req\s+zone=" + ZONE + r"\b", body), body
    assert re.search(r"limit_req_status\s+429\s*;", body), body
    # Still proxied, or the limit would be the least of the problems.
    assert re.search(r"proxy_pass\s+http://backend:8000\s*;", body), body


def test_the_generic_api_location_is_not_limited():
    """The dashboard's reads go through here and must never see a 429."""
    body = _location_body(_conf(), "/api/")

    assert "limit_req" not in body
