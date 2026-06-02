"""
Resources API Routes
====================
GET   /resources/search   — (mounted at /search under /resources prefix)
POST  /resources/seed     — Seed ChromaDB (mounted at /seed)
GET   /resources/topics   — List indexed topics (mounted at /topics)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from core.dependencies import get_current_user
from models.user import User
from services.vector_store import vector_store
from agents.orchestrator import DevBrainState
from agents.resource_agent import resource_agent_node, seed_resource_collection

logger = logging.getLogger(__name__)
router = APIRouter(tags=["resources"])

# ─────────────────────────────────────────────────────────────────────────────
# Response schemas
# ─────────────────────────────────────────────────────────────────────────────


class ResourceItem(BaseModel):
    title: str
    url: str
    difficulty: str
    source: str
    why_recommended: str


class ResourceSearchResponse(BaseModel):
    topic: str
    skill_level: str
    resources: list[ResourceItem]
    learning_path: str


class SeedResponse(BaseModel):
    seeded: int
    total: int = 0
    hint: str | None = None


class TopicsResponse(BaseModel):
    topics: list[str]


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────


@router.get(
    "/search",
    response_model=ResourceSearchResponse,
    summary="Search for learning resources on a given topic",
)
async def search_resources(
    topic: str = Query(..., description="Programming topic to search resources for"),
    difficulty: str | None = Query(
        None,
        description="Optional difficulty override: beginner | intermediate | advanced",
    ),
    current_user: User = Depends(get_current_user),
) -> ResourceSearchResponse:
    """
    Runs the resource_agent_node pipeline:

    1. Extracts canonical topic name via Grok.
    2. Checks ChromaDB for high-confidence matches.
    3. Falls back to Tavily web search if needed.
    4. Returns ranked resources + a learning-path narrative.
    """
    if not topic.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="topic query parameter must not be empty.",
        )

    # Build a minimal DevBrainState — resource_agent_node is self-contained
    initial_state = DevBrainState(
        user=current_user,
        user_input=topic,
        structured_output={
            "skill_profile": _extract_skill_profile(current_user),
            # Allow the caller to override the difficulty
            **({"forced_difficulty": difficulty} if difficulty else {}),
        },
        agent_output="",
        conversation_history=[],
        iteration_count=0,
        reflection_score=1.0,
        max_iterations=1,
        task_type="resource_search",
        metadata={},
    )

    try:
        final_state = await resource_agent_node(initial_state)
    except Exception as exc:
        logger.error("resource_agent_node failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Resource search failed: {exc}",
        )

    output: dict = final_state.get("structured_output") or {}
    raw_resources: list[dict] = output.get("resources", [])

    return ResourceSearchResponse(
        topic=output.get("topic", topic),
        skill_level=output.get("skill_level", "intermediate"),
        resources=[
            ResourceItem(
                title=r.get("title", ""),
                url=r.get("url", ""),
                difficulty=r.get("difficulty", "intermediate"),
                source=r.get("source", ""),
                why_recommended=r.get("why_recommended", ""),
            )
            for r in raw_resources
        ],
        learning_path=output.get("learning_path", ""),
    )


def _extract_skill_profile(user: User) -> dict:
    """Safe extraction of the skill profile dict from the User ORM object."""
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


# ─────────────────────────────────────────────────────────────────────────────


@router.post(
    "/seed",
    response_model=SeedResponse,
    status_code=status.HTTP_200_OK,
    summary="Seed ChromaDB with curated resources (dev/admin only, no auth required)",
)
async def seed_resources() -> SeedResponse:
    """
    Idempotent seed endpoint for development / CI setup.
    Calls seed_resource_collection() from resource_agent, which upserts
    20 hand-curated resources into ChromaDB.

    Note: In production, protect this endpoint with an admin API key or
    remove it from the public router entirely.
    """
    try:
        from agents.resource_agent import _SEED_RESOURCES

        seeded_count, errors = await seed_resource_collection()
    except Exception as exc:
        logger.error("Seeding failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Seed operation failed: {exc}",
        )

    hint = None
    if seeded_count == 0:
        hint = errors[0] if errors else "Restart uvicorn after code changes, then try again."

    return SeedResponse(
        seeded=seeded_count,
        total=len(_SEED_RESOURCES),
        hint=hint,
    )


# ─────────────────────────────────────────────────────────────────────────────


@router.get(
    "/topics",
    response_model=TopicsResponse,
    summary="List all topics currently indexed in ChromaDB",
)
async def list_topics(
    current_user: User = Depends(get_current_user),
) -> TopicsResponse:
    """
    Reads the ChromaDB resource collection's metadata to enumerate unique
    topic tags.  Returns them sorted alphabetically.
    """
    try:
        topics = await vector_store.list_resource_topics()
    except Exception as exc:
        logger.error("Failed to list topics from vector store: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not retrieve topics: {exc}",
        )

    # Normalise: replace underscores with spaces for readability
    display_topics = sorted(
        {t.replace("_", " ").title() for t in topics if t}
    )
    return TopicsResponse(topics=display_topics)
