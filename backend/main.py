"""
MinerU Enterprise - Backend Entry Point
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app.core.config import settings
from app.core.database import init_db
from app.api.v1.router import api_router
from app.api.v1.endpoints.extract import router as extract_router
from app.api.v1.endpoints.agent import router as agent_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="MinerU Enterprise API",
    description="Enterprise-grade MinerU document parsing platform",
    version="1.0.0",
    docs_url="/api/docs" if settings.DEBUG else None,
    redoc_url="/api/redoc" if settings.DEBUG else None,
    lifespan=lifespan,
)

# IMPORTANT: Middleware order matters — FastAPI uses an onion model.
# The LAST middleware added is the OUTERMOST (runs first on request).
# CORS must be the outermost layer so OPTIONS preflight requests are
# handled BEFORE any other middleware (like TrustedHost) can reject them.

if not settings.DEBUG:
    # Inner layer: validate Host header on real requests
    # Only add TrustedHostMiddleware if ALLOWED_HOSTS is explicitly configured
    if settings.ALLOWED_HOSTS:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.ALLOWED_HOSTS)

# Outer layer: CORS — must wrap everything else to handle preflight
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")

# MinerU official compatible APIs — mounted at their own prefixes
app.include_router(extract_router)   # /api/v4/extract/...
app.include_router(agent_router)     # /api/v1/agent/...


@app.get("/health")
async def health_check():
    return {"status": "ok", "version": "1.0.0"}
