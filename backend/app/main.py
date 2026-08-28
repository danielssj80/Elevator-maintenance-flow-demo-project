from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.telemetry import configure_telemetry, get_tracer, shutdown_telemetry
from app.database import AsyncSessionLocal
from app.routers import elevators
from app.seed import seed_database

tracer = get_tracer(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    with tracer.start_as_current_span("startup.seed_database"):
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await seed_database(session)
    yield
    shutdown_telemetry()


app = FastAPI(title="Elevator Maintenance API", version="0.1.0", lifespan=lifespan)

# Before middleware and routers: FastAPI instrumentation wraps the ASGI app, so
# it must be installed before anything else takes a reference to it.
configure_telemetry(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(elevators.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
