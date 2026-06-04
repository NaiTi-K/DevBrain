"""
backend/main.py
DevBrain API — FastAPI application entry point.
"""

import logging
import os
import traceback

# Must be set before chromadb is imported (suppresses broken posthog telemetry on Windows)
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routes.auth import router as auth_router
from api.routes.github import router as github_router
from api.routes.roadmap import router as roadmap_router
from api.routes.challenges import router as challenges_router
from api.routes.review import router as review_router
from api.routes.interview import router as interview_router
from api.routes.resources import router as resources_router
from api.routes.progress import router as progress_router
from code_reviewer.review_routes import router as code_reviewer_router
from core.config import settings
from models.database import Base, engine


# ── Application lifespan ──────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


# ── Application factory ───────────────────────────────────────────────────────

app = FastAPI(
    title="DevBrain API",
    version="1.0.0",
    description=(
        "AI-powered developer growth platform. "
        "Analyses your GitHub repos, builds a skill profile, and drives "
        "personalised learning via roadmaps, challenges, code review, and mock interviews."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# Build allowed origins from settings + always include localhost for dev
_cors_origins = list(
    {
        settings.FRONTEND_URL,
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    }
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("devbrain")

# ── Global exception handler ─────────────────────────────────────────────────
# FastAPI's CORSMiddleware does NOT add CORS headers when an unhandled
# exception causes a 500.  This handler catches everything, logs the full
# traceback to the console, and returns a proper JSON error WITH CORS headers
# so the browser console shows the real message instead of a misleading
# "CORS policy" error.


@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception):
    tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
    logger.error("Unhandled exception on %s %s:\n%s", request.method, request.url, "".join(tb))
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)},
    )


# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(auth_router, prefix="/auth")
app.include_router(github_router, prefix="/github")
app.include_router(roadmap_router, prefix="/roadmap")
app.include_router(challenges_router, prefix="/challenges")
app.include_router(review_router, prefix="/review")
app.include_router(interview_router, prefix="/interview")
app.include_router(resources_router, prefix="/resources")
app.include_router(progress_router, prefix="/progress")
app.include_router(code_reviewer_router, prefix="/code-reviewer", tags=["code-reviewer"])


# ── Health check ──────────────────────────────────────────────────────────────


@app.get("/health", tags=["meta"], summary="Service health check")
async def health():
    return {"status": "ok", "model": settings.GROK_MODEL}
