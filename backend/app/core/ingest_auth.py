"""The shared secret guarding the two write endpoints.

The production gate in ``main.py`` removes these routers entirely when the
deployment environment is production. It says nothing about who may write in the
environments where they *are* registered, and the orchestration change puts a
scheduled producer in front of both of them. This is that guard.

**Fail-open, deliberately, and this is the one place to argue about it.** The
production gate is fail-closed because forgetting to configure it publishes
unauthenticated write endpoints on the internet. This token is the opposite
case: it only ever runs on routers that do not exist in production, and a
fail-closed default would break ``pytest`` and a bare ``uvicorn`` run for anyone
with no configuration at all. So an unset token means open — and every
environment that registers the routers configures one, which
``tests/unit/test_dev_compose.py`` asserts against the compose file rather than
against a fixture. A guard proven only in a fixture is exactly what round 3 of
the previous change found unenforced in the deployed configuration.
"""

import secrets
from typing import Annotated

from fastapi import Header, HTTPException

from app.core.config import settings

# One message for both "absent" and "wrong". Distinguishing them would turn the
# endpoint into an oracle for whether a guard is configured at all.
UNAUTHORIZED_DETAIL = "Invalid or missing X-Ingest-Token"


async def require_ingest_token(
    x_ingest_token: Annotated[str | None, Header()] = None,
) -> None:
    """Reject the request unless it carries the configured token.

    Reads the setting per request rather than capturing it at import time, so
    the guard can be exercised in both states without rebuilding the app.
    """
    configured = settings.telemetry_ingest_token
    if not configured:
        return

    # Both sides encoded: ``compare_digest`` raises TypeError on a str
    # containing non-ASCII, and the header is attacker-controlled — a 500 from
    # a stray byte would be a worse outcome than the 401 it should have been.
    if x_ingest_token is None or not secrets.compare_digest(
        x_ingest_token.encode("utf-8"), configured.encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail=UNAUTHORIZED_DETAIL)
