from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.database import AsyncSessionLocal
from app.routers import elevators
from app.seed import seed_database


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await seed_database(session)
    yield


app = FastAPI(title="Elevator Maintenance API", version="0.1.0", lifespan=lifespan)

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
