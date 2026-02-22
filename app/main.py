from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.env_loader import load_project_env

load_project_env()

from app.api.routes_detect import router as detect_router
from app.api.routes_health import router as health_router
from app.api.routes_history import router as history_router
from app.api.routes_simulate import router as simulate_router
from app.services.history_store import init_db

app = FastAPI(title="TruthCast MVP", version="0.1.0")
init_db()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(detect_router)
app.include_router(simulate_router)
app.include_router(history_router)
