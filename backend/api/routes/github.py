# Replace the stub in main.py with: from api.routes.github import router as github_router

"""
GitHub Routes
=============
POST /github/analyze  — trigger skill-profile analysis (rate-limited: 5/hour)
GET  /github/profile  — return the latest cached/persisted skill profile
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agents.github_analyzer import SkillProfileResponse, github_analyzer_node
from agents.orchestrator import DevBrainState
from core.dependencies import get_current_user, get_db
from models.skill_profile import SkillProfile
from models.user import User
from services.cache_service import cache

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Request body ──────────────────────────────────────────────────────────


class AnalyzeRequest(BaseModel):
    github_token: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════════ #
# POST /github/analyze                                                       #
# ══════════════════════════════════════════════════════════════════════════ #


@router.post(
    "/analyze",
    response_model=SkillProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Analyse the authenticated user's GitHub repositories",
)
async def analyze_github(
    body: AnalyzeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Triggers a full GitHub skill-profile analysis.

    Rate-limited to **5 analyses per user per hour** via Redis.
    If the user supplies a personal access token it will be used instead of
    the server-side `GITHUB_PAT` setting (useful for private repos).
    """
    user_id = str(current_user.id)
    rate_key = f"rate_limit:github_analyze:{user_id}"

    # ── Rate-limit check ──────────────────────────────────────────────────
    count = await cache.increment(rate_key, ttl=3600)
    if count > 5:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="GitHub analysis rate limit reached (5 per hour). Please wait before retrying.",
        )

    if not current_user.github_username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No GitHub username linked to your account. Update your profile first.",
        )

    # ── Build initial graph state ─────────────────────────────────────────
    initial_state: DevBrainState = {
        "user_id": user_id,
        "github_username": current_user.github_username,
        "intent": "github_analyze",
        "current_agent": "github_analyzer",
        "user_input": body.github_token or "",
        "agent_output": "",
        "structured_output": {},
        "skill_profile": {},
        "conversation_history": [],
        "rag_context": [],
        "reflection_score": 0.0,
        "iteration_count": 0,
        "max_iterations": 3,
        "error": None,
        "should_continue": True,
        "force_refresh": True,
    }

    # ── Run only the analyzer node (bypass full graph for direct invocation)
    final_state = await github_analyzer_node(initial_state)

    if final_state.get("error"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Analysis failed: {final_state['error']}",
        )

    structured = final_state.get("structured_output", {})
    skills = structured.get("skills", {})
    repo_count = structured.get("repo_count", 0)
    summary = structured.get("summary", "")
    analyzed_at = datetime.utcnow()

    # Persist on the request DB session so GET /github/profile sees the row immediately.
    result = await db.execute(select(SkillProfile).where(SkillProfile.user_id == current_user.id))
    profile = result.scalar_one_or_none()
    if profile:
        profile.skills = skills
        profile.repo_count = repo_count
        profile.summary = summary
        profile.analyzed_at = analyzed_at
    else:
        db.add(
            SkillProfile(
                user_id=current_user.id,
                skills=skills,
                repo_count=repo_count,
                summary=summary,
                analyzed_at=analyzed_at,
            )
        )
    await db.flush()

    return SkillProfileResponse(
        user_id=str(current_user.id),
        github_username=current_user.github_username,
        skills=skills,
        summary=summary,
        repo_count=repo_count,
        analyzed_at=analyzed_at,
    )


# ══════════════════════════════════════════════════════════════════════════ #
# GET /github/profile                                                        #
# ══════════════════════════════════════════════════════════════════════════ #


@router.get(
    "/profile",
    response_model=SkillProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Return the latest analysed skill profile for the current user",
)
async def get_github_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns the persisted SkillProfile from PostgreSQL.
    Returns **404** if the user has never run an analysis.
    """
    result = await db.execute(
        select(SkillProfile)
        .where(SkillProfile.user_id == current_user.id)
        .options(selectinload(SkillProfile.user))
        .order_by(SkillProfile.analyzed_at.desc())
        .limit(1)
    )
    profile: Optional[SkillProfile] = result.scalar_one_or_none()

    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No skill profile found. Run POST /github/analyze first.",
        )

    return SkillProfileResponse(
        user_id=str(profile.user_id),
        github_username=current_user.github_username,
        skills=profile.skills,
        summary=profile.summary or "",
        repo_count=profile.repo_count or 0,
        analyzed_at=profile.analyzed_at,
    )
