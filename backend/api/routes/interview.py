"""
Interview API Routes
====================
POST  /interview/start                  — Start a new interview session (auth required)
POST  /interview/{session_id}/message   — Send an answer; get feedback + next question
GET   /interview/{session_id}/report    — Retrieve the final session report
GET   /interview/history                — Last 5 sessions with scores (auth required)
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from core.dependencies import get_current_user, get_db
from models.interview import InterviewSession
from models.user import User
from agents.orchestrator import DevBrainState
from agents.interview_agent import interview_agent_node

logger = logging.getLogger(__name__)
router = APIRouter(tags=["interview"])

# ─────────────────────────────────────────────────────────────────────────────
# Request / response schemas
# ─────────────────────────────────────────────────────────────────────────────


class StartInterviewRequest(BaseModel):
    mode: Literal["dsa", "system_design"] = Field(
        ..., description="Interview mode: 'dsa' for coding problems, 'system_design' for architecture."
    )


class StartInterviewResponse(BaseModel):
    session_id: str
    first_question: str
    mode: str


class SendMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, description="User's answer to the current question.")


class EvaluationSchema(BaseModel):
    score: int
    feedback: str
    model_answer: str
    next_difficulty: str
    key_concepts_missed: list[str] = []


class SendMessageResponse(BaseModel):
    response: str
    evaluation: EvaluationSchema | None = None
    session_complete: bool
    report: dict | None = None


class SessionReportResponse(BaseModel):
    session_id: str
    mode: str
    overall_score: float
    strengths: list[str]
    weak_areas: list[str]
    recommended_topics: list[str]
    summary: str
    interview_readiness: str
    completed_at: datetime


class InterviewHistoryItem(BaseModel):
    session_id: str
    mode: str
    overall_score: float | None
    total_turns: int
    completed: bool
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _extract_skill_profile(user: User) -> dict:
    try:
        if user and hasattr(user, "skill_profile") and user.skill_profile:
            raw = getattr(user.skill_profile, "skills", {}) or {}
            return {
                k: float(v.get("score", v) if isinstance(v, dict) else v)
                for k, v in raw.items()
            }
    except Exception:
        pass
    return {}


def _load_history(session: InterviewSession) -> list[dict]:
    """Deserialise conversation_history from the DB model."""
    raw = session.conversation_history or []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = []
    return raw if isinstance(raw, list) else []


def _load_structured_output(session: InterviewSession) -> dict:
    """Deserialise the structured_output JSONB column."""
    raw = session.structured_output or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = {}
    return raw if isinstance(raw, dict) else {}


async def _get_session_or_404(
    session_id: str,
    user_id: str,
    db: AsyncSession,
) -> InterviewSession:
    """Load an InterviewSession belonging to the given user, or raise 404."""
    result = await db.execute(
        select(InterviewSession).where(
            InterviewSession.id == session_id,
            InterviewSession.user_id == user_id,
        )
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Interview session '{session_id}' not found.",
        )
    return session


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────


@router.post(
    "/start",
    response_model=StartInterviewResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a new interview session and receive the first question",
)
async def start_interview(
    body: StartInterviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StartInterviewResponse:
    """
    Creates a new InterviewSession in PostgreSQL, runs interview_agent_node
    with an empty history to generate the first question, then persists
    the updated state.
    """
    session_id = str(uuid.uuid4())
    skill_profile = _extract_skill_profile(current_user)

    initial_state = DevBrainState(
        user=current_user,
        user_input="",
        structured_output={
            "mode": body.mode,
            "skill_profile": skill_profile,
            "used_topics": [],
            "current_question": {},
            "current_difficulty": "medium",
        },
        agent_output="",
        conversation_history=[],
        iteration_count=0,
        reflection_score=1.0,
        max_iterations=1,
        task_type="interview",
        metadata={"session_id": session_id},
    )

    try:
        final_state = await interview_agent_node(initial_state)
    except Exception as exc:
        logger.error("interview_agent_node failed on start: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start interview session: {exc}",
        )

    first_question: str = final_state.get("agent_output", "")
    updated_structured: dict = final_state.get("structured_output") or {}
    updated_history: list = final_state.get("conversation_history") or []

    # Persist new session
    try:
        db_session = InterviewSession(
            id=session_id,
            user_id=str(current_user.id),
            mode=body.mode,
            conversation_history=updated_history,
            structured_output=updated_structured,
            overall_score=None,
            completed=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(db_session)
        await db.commit()
        await db.refresh(db_session)
    except Exception as exc:
        logger.error("Failed to persist new interview session: %s", exc)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Session created but could not be saved. Please try again.",
        )

    return StartInterviewResponse(
        session_id=session_id,
        first_question=first_question,
        mode=body.mode,
    )


# ─────────────────────────────────────────────────────────────────────────────


@router.post(
    "/{session_id}/message",
    response_model=SendMessageResponse,
    summary="Send an answer and receive feedback + the next question",
)
async def send_message(
    session_id: str = Path(..., description="Session UUID from /interview/start"),
    body: SendMessageRequest = ...,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SendMessageResponse:
    """
    Loads the existing session, appends the user's answer, runs the
    interview_agent_node, and saves the updated state.

    Returns evaluation scores if not the first message, and signals
    session_complete when 5 Q&A rounds have been completed.
    """
    db_session = await _get_session_or_404(session_id, str(current_user.id), db)

    if db_session.completed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This interview session is already complete. See /interview/{session_id}/report.",
        )

    history = _load_history(db_session)
    structured = _load_structured_output(db_session)
    skill_profile = _extract_skill_profile(current_user)
    structured.setdefault("skill_profile", skill_profile)

    state = DevBrainState(
        user=current_user,
        user_input=body.message,
        structured_output=structured,
        agent_output="",
        conversation_history=history,
        iteration_count=0,
        reflection_score=1.0,
        max_iterations=1,
        task_type="interview",
        metadata={"session_id": session_id},
    )

    try:
        final_state = await interview_agent_node(state)
    except Exception as exc:
        logger.error("interview_agent_node failed for session %s: %s", session_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Interview agent error: {exc}",
        )

    updated_structured: dict = final_state.get("structured_output") or {}
    updated_history: list = final_state.get("conversation_history") or []
    agent_response: str = final_state.get("agent_output", "")
    session_complete: bool = updated_structured.get("session_complete", False)
    evaluation_raw: dict | None = updated_structured.get("evaluation")
    final_report: dict | None = updated_structured.get("final_report")

    # Compute overall score from report if session just completed
    overall_score: float | None = None
    if session_complete and final_report:
        overall_score = float(final_report.get("overall_score", 0.0))

    # Persist updated session
    try:
        db_session.conversation_history = updated_history
        db_session.structured_output = updated_structured
        db_session.completed = session_complete
        db_session.overall_score = overall_score
        db_session.updated_at = datetime.utcnow()
        if session_complete:
            db_session.completed_at = datetime.utcnow()
        await db.commit()
    except Exception as exc:
        logger.error("Failed to update interview session %s: %s", session_id, exc)
        await db.rollback()
        # Return the response anyway — don't fail the user's turn
        logger.warning("State persistence failed; returning response without saving.")

    # Build evaluation schema
    evaluation_schema: EvaluationSchema | None = None
    if evaluation_raw:
        evaluation_schema = EvaluationSchema(
            score=int(evaluation_raw.get("score", 0)),
            feedback=evaluation_raw.get("feedback", ""),
            model_answer=evaluation_raw.get("model_answer", ""),
            next_difficulty=evaluation_raw.get("next_difficulty", "same"),
            key_concepts_missed=evaluation_raw.get("key_concepts_missed", []),
        )

    return SendMessageResponse(
        response=agent_response,
        evaluation=evaluation_schema,
        session_complete=session_complete,
        report=final_report,
    )


# ─────────────────────────────────────────────────────────────────────────────


@router.get(
    "/{session_id}/report",
    response_model=SessionReportResponse,
    summary="Get the final performance report for a completed session",
)
async def get_session_report(
    session_id: str = Path(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionReportResponse:
    """
    Returns the end-of-session performance report.
    Raises HTTP 400 if the session is still in progress.
    """
    db_session = await _get_session_or_404(session_id, str(current_user.id), db)

    if not db_session.completed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Session is not yet complete. Answer all questions first.",
        )

    structured = _load_structured_output(db_session)
    report: dict = structured.get("final_report") or {}

    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Final report not found for this session.",
        )

    return SessionReportResponse(
        session_id=session_id,
        mode=db_session.mode,
        overall_score=float(report.get("overall_score", 0.0)),
        strengths=report.get("strengths", []),
        weak_areas=report.get("weak_areas", []),
        recommended_topics=report.get("recommended_topics", []),
        summary=report.get("summary", ""),
        interview_readiness=report.get("interview_readiness", "not ready"),
        completed_at=db_session.completed_at or db_session.updated_at or datetime.utcnow(),
    )


# ─────────────────────────────────────────────────────────────────────────────


@router.get(
    "/history",
    response_model=list[InterviewHistoryItem],
    summary="Get the last 5 interview sessions for the authenticated user",
)
async def get_interview_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[InterviewHistoryItem]:
    """Returns the 5 most recent sessions, including score if completed."""
    try:
        result = await db.execute(
            select(InterviewSession)
            .where(InterviewSession.user_id == str(current_user.id))
            .order_by(desc(InterviewSession.created_at))
            .limit(5)
        )
        sessions: list[InterviewSession] = result.scalars().all()
    except Exception as exc:
        logger.error("Failed to fetch interview history: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not retrieve interview history.",
        )

    return [
        InterviewHistoryItem(
            session_id=str(s.id),
            mode=s.mode,
            overall_score=float(s.overall_score) if s.overall_score is not None else None,
            total_turns=len(_load_history(s)),
            completed=s.completed or False,
            created_at=s.created_at,
        )
        for s in sessions
    ]