# Replace the stub in main.py with: from api.routes.progress import router as progress_router

"""
Progress Routes
===============
GET /progress/dashboard   — full analytics dashboard (runs progress agent)
GET /progress/snapshots   — daily snapshot history (default: last 30 days)
GET /progress/streak      — current streak and last activity date
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import select

from agents.progress_agent import progress_agent_node, _calculate_consecutive_streaks
from agents.github_analyzer import SkillProfileResponse
from api.routes.auth import UserResponse
from core.dependencies import get_current_user, get_db
from models import (
    User,
    ProgressSnapshot,
    ChallengeAttempt,
    CodeReview,
    InterviewSession,
)
from services.cache_service import cache

logger = logging.getLogger(__name__)

router = APIRouter(tags=["progress"])

# ── Response schemas ──────────────────────────────────────────────────────


class StreakInfo(BaseModel):
    current_streak: int
    longest_streak: int
    last_activity_date: Optional[date] = None


class SkillDelta(BaseModel):
    skill: str
    delta_7d: float
    delta_30d: float
    current_score: float


class DailyActivity(BaseModel):
    date: str  # YYYY-MM-DD
    challenges_solved: int
    reviews_submitted: int
    interview_sessions: int
    total_activity: int


class TrendPoint(BaseModel):
    date: str  # YYYY-MM-DD
    score: float


class RoadmapTracker(BaseModel):
    id: str
    target_role: str
    total_weeks: int
    completed_weeks: int
    percent_completed: float
    total_topics: int = 0
    completed_topics: int = 0


class DashboardResponse(BaseModel):
    user: UserResponse
    streak: StreakInfo
    skill_profile: Optional[SkillProfileResponse] = None
    skill_deltas: list[SkillDelta]
    total_challenges_solved: int
    total_reviews_submitted: int
    total_interview_sessions: int
    exam_readiness_score: float
    exam_readiness: dict[str, int]
    weekly_digest: str
    daily_activity: list[DailyActivity]
    trend_data: list[TrendPoint]
    weekly_challenge_goal: int
    weekly_challenges_done: int
    roadmap_tracker: Optional[RoadmapTracker] = None


class SnapshotItem(BaseModel):
    snapshot_date: date
    skills: dict[str, float]
    challenges_done: int
    challenges_passed: int

    class Config:
        from_attributes = True


class StreakResponse(BaseModel):
    streak_days: int
    last_activity: Optional[date] = None


# ══════════════════════════════════════════════════════════════════════════ #
# GET /progress/dashboard                                                    #
# ══════════════════════════════════════════════════════════════════════════ #


@router.get(
    "/dashboard",
    response_model=DashboardResponse,
    status_code=status.HTTP_200_OK,
    summary="Full analytics dashboard — skill deltas, streak, exam readiness, digest",
)
async def get_dashboard(
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Runs the progress agent to compute and return all analytics for the
    authenticated user.  Also upserts today's ProgressSnapshot.
    """
    user_id = str(current_user.id)

    cached_dashboard = await cache.get_progress_dashboard(user_id)
    if cached_dashboard:
        try:
            return DashboardResponse(**cached_dashboard)
        except Exception:
            await cache.delete_progress_dashboard(user_id)

    # Resolve current skill profile from cache
    skill_profile: dict = {}
    cached = await cache.get_skill_profile(user_id)
    if cached:
        skill_profile = {
            "skills": cached.get("skills", {}),
            "summary": cached.get("summary", ""),
            "frameworks": cached.get("frameworks", {}),
            "engineering_practices": cached.get("engineering_practices", {}),
            "repo_highlights": cached.get("repo_highlights", []),
        }

    state = {
        "user_id": user_id,
        "github_username": current_user.github_username or "",
        "intent": "progress",
        "current_agent": "progress_agent",
        "user_input": "",
        "agent_output": "",
        "structured_output": {},
        "skill_profile": skill_profile,
        "conversation_history": [],
        "rag_context": [],
        "reflection_score": 0.0,
        "iteration_count": 0,
        "max_iterations": 3,
        "error": None,
        "should_continue": True,
    }

    final_state = await progress_agent_node(state)
    structured = final_state.get("structured_output", {})

    if "user" not in structured or not structured["user"]:
        structured["user"] = {
            "id": str(current_user.id),
            "github_id": current_user.github_id,
            "username": current_user.github_username or "",
            "email": None,
            "avatar_url": current_user.avatar_url,
            "name": current_user.display_name,
            "created_at": current_user.created_at.isoformat() if current_user.created_at else "",
            "updated_at": current_user.created_at.isoformat() if current_user.created_at else "",
        }

    response = DashboardResponse(**structured)
    await cache.set_progress_dashboard(user_id, response.model_dump(mode="json"))
    return response


# ══════════════════════════════════════════════════════════════════════════ #
# GET /progress/snapshots                                                    #
# ══════════════════════════════════════════════════════════════════════════ #


@router.get(
    "/snapshots",
    response_model=list[SnapshotItem],
    status_code=status.HTTP_200_OK,
    summary="Return daily progress snapshots for the last N days",
)
async def get_snapshots(
    days: int = Query(default=30, ge=1, le=365, description="Number of past days to return"),
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Returns daily `ProgressSnapshot` records for the authenticated user,
    sorted ascending by date (oldest first).
    """
    cutoff = (datetime.utcnow() - timedelta(days=days)).date()

    result = await db.execute(
        select(ProgressSnapshot)
        .where(
            ProgressSnapshot.user_id == current_user.id,
            ProgressSnapshot.snapshot_date >= cutoff,
        )
        .order_by(ProgressSnapshot.snapshot_date.asc())
    )
    snapshots = result.scalars().all()

    return [
        SnapshotItem(
            snapshot_date=s.snapshot_date,
            skills=s.skills or {},
            challenges_done=s.challenges_done,
            challenges_passed=s.challenges_passed,
        )
        for s in snapshots
    ]


# ══════════════════════════════════════════════════════════════════════════ #
# GET /progress/streak                                                       #
# ══════════════════════════════════════════════════════════════════════════ #


@router.get(
    "/streak",
    response_model=StreakResponse,
    status_code=status.HTTP_200_OK,
    summary="Current activity streak and date of last recorded activity",
)
async def get_streak(
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Computes the current consecutive-day streak dynamically across challenge attempts,
    code reviews, and technical interview sessions.
    """
    user_id = current_user.id

    att_res = await db.execute(select(ChallengeAttempt.attempted_at).where(ChallengeAttempt.user_id == user_id))
    rev_res = await db.execute(select(CodeReview.created_at).where(CodeReview.user_id == user_id))
    iv_res = await db.execute(select(InterviewSession.created_at).where(InterviewSession.user_id == user_id))

    active_dates = set()
    for row in att_res.scalars().all():
        active_dates.add(row.date())
    for row in rev_res.scalars().all():
        active_dates.add(row.date())
    for row in iv_res.scalars().all():
        active_dates.add(row.date())

    current_streak, longest_streak, last_act = _calculate_consecutive_streaks(active_dates)

    return StreakResponse(
        streak_days=current_streak,
        last_activity=last_act,
    )
