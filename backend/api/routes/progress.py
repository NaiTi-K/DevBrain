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

from agents.progress_agent import progress_agent_node
from core.dependencies import get_current_user, get_db
from models.progress import ProgressSnapshot
from models.user import User
from services.cache_service import cache

logger = logging.getLogger(__name__)

router = APIRouter(tags=["progress"])

# ── Response schemas ──────────────────────────────────────────────────────


class DashboardResponse(BaseModel):
    skill_delta_7d: dict[str, float]
    skill_delta_30d: dict[str, float]
    streak: int
    exam_readiness: dict[str, int]
    challenge_pass_rate: float
    weekly_digest: str


class SnapshotItem(BaseModel):
    snapshot_date: date
    skills: dict[str, float]
    challenges_done: int
    challenges_passed: int

    class Config:
        from_attributes = True


class StreakResponse(BaseModel):
    streak_days: int
    last_activity: Optional[date]


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
        return DashboardResponse(**cached_dashboard)

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
    response = DashboardResponse(
        skill_delta_7d=structured.get("skill_delta_7d", {}),
        skill_delta_30d=structured.get("skill_delta_30d", {}),
        streak=structured.get("streak", 0),
        exam_readiness=structured.get("exam_readiness", {}),
        challenge_pass_rate=structured.get("challenge_pass_rate", 0.0),
        weekly_digest=structured.get("weekly_digest", "No digest available yet."),
    )
    await cache.set_progress_dashboard(user_id, response.model_dump())
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
    Computes the current consecutive-day streak (days with ≥ 1 challenge done)
    and returns the date of the most recent recorded activity.
    """
    # Load last 90 days of snapshots (enough for any reasonable streak)
    cutoff = (datetime.utcnow() - timedelta(days=90)).date()
    result = await db.execute(
        select(ProgressSnapshot)
        .where(
            ProgressSnapshot.user_id == current_user.id,
            ProgressSnapshot.snapshot_date >= cutoff,
            ProgressSnapshot.challenges_done > 0,
        )
        .order_by(ProgressSnapshot.snapshot_date.desc())
    )
    active_snapshots = result.scalars().all()

    if not active_snapshots:
        return StreakResponse(streak_days=0, last_activity=None)

    # Compute streak from the most recent activity day backwards
    today = datetime.utcnow().date()
    streak = 0
    check_date = active_snapshots[0].snapshot_date  # most recent active day

    # Allow streak to start from today or yesterday
    if check_date < today - timedelta(days=1):
        # Streak is broken — most recent activity was 2+ days ago
        return StreakResponse(streak_days=0, last_activity=check_date)

    active_dates = {s.snapshot_date for s in active_snapshots}
    current = check_date
    while current in active_dates:
        streak += 1
        current -= timedelta(days=1)

    return StreakResponse(
        streak_days=streak,
        last_activity=active_snapshots[0].snapshot_date,
    )
