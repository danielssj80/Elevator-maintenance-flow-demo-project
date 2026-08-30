import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.metrics import refresh_snapshot_periodically, register_instruments
from app.core.telemetry import configure_telemetry, get_tracer, shutdown_telemetry
from app.database import AsyncSessionLocal
from app.routers import elevators, inference, telemetry
from app.seed import seed_database
from app.services.inference_service import FeatureBuildError

logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    with tracer.start_as_current_span("startup.seed_database"):
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await seed_database(session)

    # The fleet-health snapshot is refreshed here because observable-gauge
    # callbacks run on the metric reader's thread, where there is no event loop
    # to await a database session on. This task is the app's only scheduler.
    refresh_task: asyncio.Task[None] | None = None
    if settings.otel_enabled:
        register_instruments()
        refresh_task = asyncio.create_task(
            refresh_snapshot_periodically(
                AsyncSessionLocal, settings.fleet_metrics_refresh_seconds
            )
        )

    yield

    if refresh_task is not None:
        refresh_task.cancel()
        # Await the cancellation so shutdown does not race the task, and
        # swallow the CancelledError it is expected to raise.
        with contextlib.suppress(asyncio.CancelledError):
            await refresh_task

    shutdown_telemetry()


def build_app(environment: str | None = None) -> FastAPI:
    """Build the application.

    ``environment`` is a parameter rather than a read of the settings singleton
    so the production gate below can be tested without mutating global state.
    It defaults to the configured deployment environment.
    """
    environment = environment if environment is not None else settings.deployment_environment

    app = FastAPI(title="Elevator Maintenance API", version="0.1.0", lifespan=lifespan)

    # Before middleware and routers: FastAPI instrumentation wraps the ASGI app,
    # so it must be installed before anything else takes a reference to it.
    configure_telemetry(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(elevators.router)

    # The telemetry and inference routers are unauthenticated write endpoints,
    # and docker-compose.prod.yml auto-deploys on merge to the default branch.
    # Registering them in production would let anyone inject telemetry and
    # re-score the live fleet. They are therefore not registered at all there —
    # not registered-and-guarded, which leaves a route to get the guard wrong on.
    #
    # Follow-up: an X-Ingest-Token header compared with secrets.compare_digest,
    # with None meaning open in dev. That is additive; this gate is what removes
    # the exposure.
    if environment != "production":
        app.include_router(telemetry.router)
        app.include_router(inference.router)

    @app.exception_handler(FeatureBuildError)
    async def _feature_build_error(request: Request, exc: FeatureBuildError) -> JSONResponse:
        """A run that cannot build a usable matrix is a server fault, but a
        described one.

        Without this the error escapes as a bare 500 with a full traceback,
        which docs/backend-standards.md names as the thing not to do. The
        message says which invariant failed; it carries no telemetry values.
        """
        logger.error("Inference run aborted: %s", exc)
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = build_app()
