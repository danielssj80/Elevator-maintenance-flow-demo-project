from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import elevators

app = FastAPI(title="Elevator Maintenance API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://frontend:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(elevators.router)


@app.get("/health")
def health():
    return {"status": "ok"}
