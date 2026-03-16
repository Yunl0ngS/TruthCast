import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.env_loader import load_project_env

load_project_env()

from app.api.routes_content import router as content_router
from app.api.chat import router as chat_router
from app.api.routes_detect import router as detect_router
from app.api.routes_export import router as export_router
from app.api.routes_health import router as health_router
from app.api.routes_history import router as history_router
from app.api.routes_multimodal import router as multimodal_router
from app.api.routes_simulate import router as simulate_router
from app.api.routes_pipeline_state import router as pipeline_router
from app.core.auth import require_api_key
from app.core.concurrency import init_semaphore
from app.core.rate_limit import RateLimitMiddleware
from app.services.history_store import init_db
from app.services.chat_store import init_db as init_chat_db


def _cors_origins() -> list[str]:
    """从环境变量读取 CORS 白名单，逗号分隔。未配置时使用开发默认值。"""
    raw = os.getenv("TRUTHCAST_CORS_ORIGINS", "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return ["http://localhost:3000", "http://127.0.0.1:3000"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时初始化
    init_db()
    init_chat_db()
    init_semaphore()
    yield
    # 关闭时清理（预留）


app = FastAPI(
    title="TruthCast MVP",
    version="0.1.0",
    lifespan=lifespan,
    dependencies=[Depends(require_api_key)],
)

# --- 限流中间件（最外层，优先执行） ---
app.add_middleware(RateLimitMiddleware)

# --- CORS ---
origins = _cors_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(detect_router)
app.include_router(chat_router)
app.include_router(simulate_router)
app.include_router(pipeline_router)
app.include_router(history_router)
app.include_router(content_router)
app.include_router(export_router)
app.include_router(multimodal_router)
