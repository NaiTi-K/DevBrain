"""
Review API Routes
=================
POST   /review/submit    — Full code review with reflection loop (auth required)
GET    /review/stream    — SSE streaming review (auth not required, token-based)
GET    /review/history   — Last 10 reviews for current user (auth required)
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from core.dependencies import get_current_user, get_db
from models.code_review import CodeReview
from models.user import User
from services.llm_service import llm
from services.vector_store import vector_store
from services.cache_service import cache
from agents.orchestrator import DevBrainState, app as langgraph_app

logger = logging.getLogger(__name__)
router = APIRouter(tags=["review"])

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

RATE_LIMIT_KEY_PREFIX = "review_ratelimit"
RATE_LIMIT_MAX = 20  # requests
RATE_LIMIT_WINDOW = 3600  # seconds (1 hour)

# ─────────────────────────────────────────────────────────────────────────────
# Request / response schemas
# ─────────────────────────────────────────────────────────────────────────────


class ReviewSubmitRequest(BaseModel):
    code: str = Field(..., min_length=1, description="Source code to review")
    language: str = Field(..., description="Programming language (e.g. python, javascript)")
    context: str = Field("", description="Optional context about what the code does")


class AnnotationSchema(BaseModel):
    line: int
    issue: str
    fix: str


class ComplexitySchema(BaseModel):
    time: str
    space: str


class ImprovementSchema(BaseModel):
    title: str
    description: str
    code_example: str


class ReviewDataSchema(BaseModel):
    score: int
    annotations: list[AnnotationSchema]
    complexity: ComplexitySchema
    edge_cases: list[str]
    improvements: list[ImprovementSchema]
    best_practices: list[str]
    summary: str


class ReviewSubmitResponse(BaseModel):
    review: dict
    reflection_loops: int
    review_id: str


class ReviewHistoryItem(BaseModel):
    review_id: str
    language: str
    score: int
    summary: str
    code_preview: str
    reflection_loops: int
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


async def _check_rate_limit(user_id: str) -> None:
    """
    Enforce 20 review submissions per user per hour using Redis.
    Raises HTTP 429 if exceeded.
    """
    key = f"{RATE_LIMIT_KEY_PREFIX}:{user_id}"
    try:
        allowed = await cache.rate_limit(key, limit=RATE_LIMIT_MAX, window=RATE_LIMIT_WINDOW)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded: {RATE_LIMIT_MAX} reviews per hour. Please wait.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        # Redis failure should not block the user — log and continue
        logger.warning("Rate-limit Redis check failed for user %s: %s", user_id, exc)


def _build_initial_state(
    user: User,
    code: str,
    language: str,
    context: str,
) -> DevBrainState:
    """Construct the initial LangGraph state for a code review run."""
    return DevBrainState(
        user_id=str(user.id),
        github_username=user.github_username or "",
        intent="review",
        current_agent="code_reviewer",
        user_input=json.dumps({"code": code, "language": language, "context": context}),
        agent_output="",
        structured_output={"code": code, "language": language, "context": context},
        skill_profile={},
        conversation_history=[],
        rag_context=[],
        reflection_score=1.0,
        iteration_count=0,
        max_iterations=3,
        error=None,
        should_continue=True,
    )


def _count_reflection_loops(final_state: DevBrainState) -> int:
    """
    The number of reflection loops = iteration_count - 1
    (first iteration is the baseline review; subsequent ones are re-reviews).
    """
    return max(0, int(final_state.get("iteration_count", 1)) - 1)


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────


@router.post(
    "/submit",
    response_model=ReviewSubmitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit code for AI review with reflection loop",
)
async def submit_review(
    body: ReviewSubmitRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReviewSubmitResponse:
    """
    Run the code through the LangGraph review pipeline:
    orchestrator → code_reviewer → reflector → (loop if quality < 0.75) → END.

    Rate limited to 20 reviews per user per hour.
    """
    await _check_rate_limit(str(current_user.id))

    # ── Build & run LangGraph ──────────────────────────────────────────────
    initial_state = _build_initial_state(
        user=current_user,
        code=body.code,
        language=body.language,
        context=body.context,
    )

    try:
        final_state: DevBrainState = await langgraph_app.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": f"review-{uuid.uuid4().hex}"}},
        )
    except Exception as exc:
        logger.error("LangGraph code review failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Review pipeline failed: {exc}",
        )

    review_dict: dict = final_state.get("structured_output") or {}
    reflection_loops = _count_reflection_loops(final_state)

    # ── Persist to PostgreSQL ──────────────────────────────────────────────
    review_id = str(uuid.uuid4())
    try:
        db_review = CodeReview(
            id=review_id,
            user_id=str(current_user.id),
            code=body.code,
            language=body.language,
            context=body.context,
            score=review_dict.get("score", 0),
            annotations=review_dict.get("annotations", []),
            complexity=review_dict.get("complexity", {}),
            edge_cases=review_dict.get("edge_cases", []),
            improvements=review_dict.get("improvements", []),
            best_practices=review_dict.get("best_practices", []),
            summary=review_dict.get("summary", ""),
            reflection_loops=reflection_loops,
            reflection_score=float(final_state.get("reflection_score", 1.0)),
            created_at=datetime.utcnow(),
        )
        db.add(db_review)
        await db.commit()
        await db.refresh(db_review)
    except Exception as exc:
        logger.error("Failed to persist CodeReview to DB: %s", exc)
        await db.rollback()
        # Non-fatal — still return the review to the user

    # ── Index in ChromaDB ──────────────────────────────────────────────────
    try:
        await vector_store.add_code_review(
            review_id=review_id,
            code=body.code,
            language=body.language,
            review_summary=review_dict.get("summary", ""),
            user_id=str(current_user.id),
        )
    except Exception as exc:
        logger.warning("Vector store indexing failed (non-fatal): %s", exc)

    return ReviewSubmitResponse(
        review=review_dict,
        reflection_loops=reflection_loops,
        review_id=review_id,
    )


# ─────────────────────────────────────────────────────────────────────────────


async def _token_stream(code: str, language: str, context: str) -> AsyncGenerator[str, None]:
    """Async generator that yields SSE-formatted chunks from llm.stream()."""
    from agents.code_review_agent import REVIEW_PROMPT, REVIEW_SYSTEM

    context_block = f"Additional context: {context}\n\n" if context else ""
    prompt = REVIEW_PROMPT.format(
        language=language,
        code=code,
        context_block=context_block,
    )

    try:
        async for token in llm.stream(prompt=prompt, system=REVIEW_SYSTEM):
            # SSE format: "data: <token>\n\n"
            yield f"data: {token}\n\n"
    except Exception as exc:
        logger.error("Streaming review failed: %s", exc)
        yield f"data: [ERROR] {exc}\n\n"
    finally:
        yield "data: [DONE]\n\n"


@router.get(
    "/stream",
    summary="Stream a code review as Server-Sent Events",
    response_class=StreamingResponse,
)
async def stream_review(
    code: str = Query(..., description="Source code to review"),
    language: str = Query(..., description="Programming language"),
    context: str = Query("", description="Optional context"),
) -> StreamingResponse:
    """
    SSE endpoint — streams Grok tokens directly to the client.

    Usage (JavaScript):
        const es = new EventSource(`/review/stream?code=...&language=python`);
        es.onmessage = e => { if (e.data === '[DONE]') es.close(); else appendToken(e.data); };
    """
    if not code.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="code must not be empty")
    if not language.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="language must not be empty")

    return StreamingResponse(
        _token_stream(code=code, language=language, context=context),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable Nginx buffering for SSE
        },
    )


# ─────────────────────────────────────────────────────────────────────────────


@router.get(
    "/history",
    response_model=list[ReviewHistoryItem],
    summary="Get the last 10 code reviews for the authenticated user",
)
async def get_review_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ReviewHistoryItem]:
    """Returns the 10 most recent code reviews, truncating code to 200 characters."""
    try:
        result = await db.execute(
            select(CodeReview)
            .where(CodeReview.user_id == str(current_user.id))
            .order_by(desc(CodeReview.created_at))
            .limit(10)
        )
        reviews: list[CodeReview] = result.scalars().all()
    except Exception as exc:
        logger.error("Failed to fetch review history: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not retrieve review history.",
        )

    return [
        ReviewHistoryItem(
            review_id=str(r.id),
            language=r.language,
            score=r.score,
            summary=r.summary or "",
            code_preview=(r.code or "")[:200],
            reflection_loops=r.reflection_loops or 0,
            created_at=r.created_at,
        )
        for r in reviews
    ]
