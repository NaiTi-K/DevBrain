"""
review_routes.py
FastAPI router for the Code Reviewer agent.
Exposes two endpoints:
  POST /code-reviewer/review  → full structured markdown review
  GET  /code-reviewer/stream  → streaming markdown review (SSE)

Both endpoints accept the same input schema.
They use DIFFERENT prompts and DIFFERENT Groq calling patterns.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

from .pre_analyzer import run_pre_analysis
from .prompts import (
    SYSTEM_PROMPT,
    STREAM_SYSTEM_PROMPT,
    build_prompt,
    build_stream_prompt,
)
from .groq_client import call_groq, stream_groq


router = APIRouter()


# ─── Request Schema ────────────────────────────────────────────────────────────


class ReviewRequest(BaseModel):
    """Input schema for both review endpoints."""

    code: str
    language: Optional[str] = None  # 'python', 'cpp', or 'java'
    context: Optional[str] = ""  # User's description of what the code does


# ─── Endpoint 1: Full Structured Review ───────────────────────────────────────


@router.post("/review")
async def review_code(request: ReviewRequest):
    """
    Full code review endpoint.
    Runs pre-analysis → builds structured prompt → calls Groq → returns markdown.
    Returns JSON with a 'review' key containing the markdown string.
    """
    # 1. Validate input
    if not request.code or not request.code.strip():
        raise HTTPException(status_code=400, detail="Code cannot be empty.")
    if len(request.code) > 50_000:
        raise HTTPException(status_code=400, detail="Code too long. Maximum 50,000 characters.")

    # 2. Run pre-analysis (fast, local, no network)
    hints = run_pre_analysis(
        code=request.code,
        language_hint=request.language,
    )

    # 3. Build the structured prompt
    prompt = build_prompt(
        code=request.code,
        hints=hints,
        user_context=request.context or "",
    )

    # 4. Call Groq (one call, returns full markdown string)
    try:
        review_markdown = await call_groq(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=prompt,
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Review service unavailable: {str(e)}")

    # 5. Return the result
    return {
        "review": review_markdown,
        "language": hints["language"],
        "lines": hints["total_lines"],
        "hints": {
            "loop_depth": hints["loop_nesting_depth"],
            "has_recursion": hints["has_recursion"],
        },
    }


# ─── Endpoint 2: Streaming Review (SSE) ───────────────────────────────────────


@router.get("/stream")
async def stream_review(code: str, language: str = "", context: str = ""):
    """
    Streaming code review endpoint using Server-Sent Events.
    Uses a simpler prompt that does NOT require pre-analysis hints.
    Streams markdown tokens as they are generated.
    """
    # 1. Validate input
    if not code or not code.strip():
        raise HTTPException(status_code=400, detail="Code cannot be empty.")

    # 2. Build the streaming prompt (NO pre-analysis, simpler prompt)
    prompt = build_stream_prompt(
        code=code,
        language=language or "code",
        user_context=context,
    )

    # 3. Define the SSE generator
    async def event_generator():
        try:
            async for chunk in stream_groq(
                system_prompt=STREAM_SYSTEM_PROMPT,
                user_prompt=prompt,
            ):
                # SSE format: each message is "data: <content>\n\n"
                # Escape newlines inside the chunk for SSE protocol
                safe_chunk = chunk.replace("\n", "\\n")
                yield f"data: {safe_chunk}\n\n"
        except Exception as e:
            # Send error as SSE event so frontend can handle it
            yield f"data: [REVIEW_ERROR]: {str(e)}\n\n"
        finally:
            # Signal stream completion
            yield "data: [REVIEW_DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ─── Health Check ─────────────────────────────────────────────────────────────


@router.get("/health")
async def health():
    """Simple health check for the code reviewer service."""
    return {"status": "ok", "agent": "code-reviewer"}
