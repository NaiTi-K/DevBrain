# Replace the stub in main.py with: from api.routes.roadmap import router as roadmap_router

"""
Roadmap Routes
==============
POST  /roadmap/generate          — generate a 6-week personalised roadmap
GET   /roadmap/current           — retrieve the user's active roadmap
PATCH /roadmap/{roadmap_id}      — partially update roadmap plan JSON
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from agents.roadmap_agent import roadmap_agent_node
from core.dependencies import get_current_user, get_db
from models.roadmap import Roadmap
from models.user import User
from services.cache_service import cache

logger = logging.getLogger(__name__)

router = APIRouter(tags=["roadmap"])

# Allowed target roles (must match frontend dropdown values)
_ALLOWED_ROLES: set[str] = {
    "SDE Intern",
    "Frontend Engineer",
    "Backend Engineer",
    "Full Stack Engineer",
    "DevOps / Platform Engineer",
    "ML / AI Engineer",
    "Data Engineer",
    "Mobile Engineer",
    "Security Engineer",
    # Keep short aliases for backward compatibility
    "Backend",
    "ML",
    "Full-Stack",
    "DevOps",
    "Frontend",
}

# ── Request / Response schemas ────────────────────────────────────────────


class GenerateRoadmapRequest(BaseModel):
    target_role: str = "SDE Intern"


class RoadmapResponse(BaseModel):
    id: str
    user_id: str
    target_role: str
    plan: dict
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class PatchRoadmapRequest(BaseModel):
    plan: dict  # partial or full replacement of the plan JSON


# ══════════════════════════════════════════════════════════════════════════ #
# POST /roadmap/generate                                                     #
# ══════════════════════════════════════════════════════════════════════════ #


@router.post(
    "/generate",
    response_model=RoadmapResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a personalised 6-week learning roadmap",
)
async def generate_roadmap(
    body: GenerateRoadmapRequest,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Generates a new roadmap tailored to the user's skill profile and target
    role. Any previously active roadmap for this user is deactivated.

    Allowed roles: `SDE Intern`, `Backend`, `ML`, `Full-Stack`, `DevOps`.
    """
    if body.target_role not in _ALLOWED_ROLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid target_role. Choose from: {', '.join(sorted(_ALLOWED_ROLES))}",
        )

    user_id = str(current_user.id)

    # Resolve skill profile from cache
    skill_profile: dict = {}
    cached = await cache.get_skill_profile(user_id)
    if cached:
        skill_profile = {
            "skills": cached.get("skills", {}),
            "frameworks": cached.get("frameworks", {}),
            "analysis_report": cached.get("analysis_report", {}),
            "engineering_practices": cached.get("engineering_practices", {}),
            "repo_highlights": cached.get("repo_highlights", []),
            "summary": cached.get("summary", ""),
        }

    state = {
        "user_id": user_id,
        "github_username": current_user.github_username or "",
        "intent": "roadmap",
        "current_agent": "roadmap_agent",
        "user_input": "",
        "agent_output": "",
        "structured_output": {"target_role": body.target_role},
        "skill_profile": skill_profile,
        "conversation_history": [],
        "rag_context": [],
        "reflection_score": 0.0,
        "iteration_count": 0,
        "max_iterations": 3,
        "error": None,
        "should_continue": True,
    }

    final_state = await roadmap_agent_node(state)

    if final_state.get("error"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Roadmap generation failed: {final_state['error']}",
        )

    # Fetch the newly created roadmap from DB for a proper response
    result = await db.execute(
        select(Roadmap)
        .where(Roadmap.user_id == current_user.id, Roadmap.is_active == True)  # noqa: E712
        .order_by(Roadmap.created_at.desc())
    )
    roadmap: Optional[Roadmap] = result.scalar_one_or_none()

    if not roadmap:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Roadmap was generated but could not be retrieved.",
        )

    return RoadmapResponse(
        id=str(roadmap.id),
        user_id=str(roadmap.user_id),
        target_role=roadmap.target_role,
        plan=roadmap.plan,
        is_active=roadmap.is_active,
        created_at=roadmap.created_at,
    )


# ══════════════════════════════════════════════════════════════════════════ #
# GET /roadmap/current                                                       #
# ══════════════════════════════════════════════════════════════════════════ #


@router.get(
    "/current",
    response_model=RoadmapResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve the user's currently active roadmap",
)
async def get_current_roadmap(
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Returns the active roadmap from PostgreSQL, or **404** if none exists.
    """
    result = await db.execute(
        select(Roadmap)
        .where(Roadmap.user_id == current_user.id, Roadmap.is_active == True)  # noqa: E712
        .order_by(Roadmap.created_at.desc())
    )
    roadmap: Optional[Roadmap] = result.scalar_one_or_none()

    if not roadmap:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active roadmap found. Run POST /roadmap/generate first.",
        )

    return RoadmapResponse(
        id=str(roadmap.id),
        user_id=str(roadmap.user_id),
        target_role=roadmap.target_role,
        plan=roadmap.plan,
        is_active=roadmap.is_active,
        created_at=roadmap.created_at,
    )


# ══════════════════════════════════════════════════════════════════════════ #
# PATCH /roadmap/{roadmap_id}                                               #
# ══════════════════════════════════════════════════════════════════════════ #


@router.patch(
    "/{roadmap_id}",
    response_model=RoadmapResponse,
    status_code=status.HTTP_200_OK,
    summary="Partially update a roadmap's plan JSON",
)
async def patch_roadmap(
    roadmap_id: str,
    body: PatchRoadmapRequest,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Merges the supplied `plan` dict into the existing roadmap plan.
    Only the owner of the roadmap may update it.
    """
    try:
        rid = uuid.UUID(roadmap_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="roadmap_id must be a valid UUID.",
        )

    result = await db.execute(
        select(Roadmap).where(Roadmap.id == rid, Roadmap.user_id == current_user.id)
    )
    roadmap: Optional[Roadmap] = result.scalar_one_or_none()

    if not roadmap:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Roadmap not found or you do not have permission to edit it.",
        )

    # Deep-merge: caller's plan keys override existing ones
    merged_plan = {**roadmap.plan, **body.plan}
    roadmap.plan = merged_plan
    await db.commit()
    await db.refresh(roadmap)

    return RoadmapResponse(
        id=str(roadmap.id),
        user_id=str(roadmap.user_id),
        target_role=roadmap.target_role,
        plan=roadmap.plan,
        is_active=roadmap.is_active,
        created_at=roadmap.created_at,
    )