"""The shared secret guarding the telemetry and inference endpoints.

``build_app`` decides whether these routers exist at all: outside production
always, in production only behind a configured token of at least 32 characters.
This guard decides who may call them once they do.

**Fail-open outside production, fail-closed in production.** With no token
configured, a local checkout and the test suite stay usable — the routers
register with a startup warning, and ``tests/unit/test_dev_compose.py`` asserts
that the development compose file configures one anyway. In production an
unset or empty token rejects every request: the gate in ``build_app`` already
withholds the routers in that case, and this is the second, independent reason
for the same outcome, covering a token cleared after startup or a future
registration path that forgets the gate. A guard proven only in a fixture is
exactly what round 3 of an earlier review found unenforced in the deployed
configuration, so the two do not lean on each other.
"""

import secrets
from typing import Annotated

from fastapi import Header, HTTPException

from app.core.config import is_production, settings

# One message for both "absent" and "wrong". Distinguishing them would turn the
# endpoint into an oracle for whether a guard is configured at all.
UNAUTHORIZED_DETAIL = "Invalid or missing X-Ingest-Token"


async def require_ingest_token(
    x_ingest_token: Annotated[str | None, Header()] = None,
) -> None:
    """Reject the request unless it carries the configured token.

    Reads the settings per request rather than capturing them at import time,
    so the guard can be exercised in every state without rebuilding the app.
    """
    configured = settings.telemetry_ingest_token
    if not configured:
        if is_production(settings.deployment_environment):
            raise HTTPException(status_code=401, detail=UNAUTHORIZED_DETAIL)
        return

    # Both sides encoded: ``compare_digest`` raises TypeError on a str
    # containing non-ASCII, and the header is attacker-controlled — a 500 from
    # a stray byte would be a worse outcome than the 401 it should have been.
    if x_ingest_token is None or not secrets.compare_digest(
        x_ingest_token.encode("utf-8"), configured.encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail=UNAUTHORIZED_DETAIL)
