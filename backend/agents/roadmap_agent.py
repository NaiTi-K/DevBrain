"""
Roadmap Agent
=============
Pipeline:
  1. Load analysis_report from skill profile cache (profile_engine output).
  2. roadmap_engine.build_roadmap_plan() → deterministic 6-week plan.
  3. LLM (optional) → polish reason/project_idea copy only.
  4. Persist to PostgreSQL.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy import update

from models.database import async_session
from models.roadmap import Roadmap
from services.cache_service import cache
from services.llm_service import llm
from services.profile_engine import build_analysis_report
from services.roadmap_engine import build_roadmap_plan, polish_roadmap_copy

logger = logging.getLogger(__name__)


async def roadmap_agent_node(state: dict) -> dict:
    """
    LangGraph node: build a structured 6-week learning roadmap.

    Requires a prior GitHub analysis (analysis_report in cache).
    """
    user_id: str = state["user_id"]

    try:
        skill_profile: dict = state.get("skill_profile") or {}
        analysis_report: dict = skill_profile.get("analysis_report", {})

        if not analysis_report:
            cached = await cache.get_skill_profile(user_id)
            if cached:
                analysis_report = cached.get("analysis_report", {})
                if not analysis_report and cached.get("skills"):
                    analysis_report = build_analysis_report(
                        cached,
                        cached.get("github_username") or state.get("github_username", ""),
                    )
                skill_profile = {
                    "skills": cached.get("skills", {}),
                    "frameworks": cached.get("frameworks", {}),
                    "analysis_report": analysis_report,
                    "engineering_practices": cached.get("engineering_practices", {}),
                    "repo_highlights": cached.get("repo_highlights", []),
                    "summary": cached.get("summary", ""),
                }

        if not analysis_report or not analysis_report.get("skills"):
            raise ValueError("No GitHub analysis found. Run POST /github/analyze before generating a roadmap.")

        structured_out = state.get("structured_output") or {}
        target_role: str = structured_out.get("target_role") or "Full Stack Engineer"

        # ── Deterministic roadmap (core logic) ─────────────────────────────
        roadmap_json = build_roadmap_plan(analysis_report, target_role)

        # ── Optional LLM polish (structure locked) ───────────────────────
        roadmap_json = await polish_roadmap_copy(roadmap_json, analysis_report, llm)

        weeks = roadmap_json.get("weeks", [])
        if len(weeks) != 6:
            raise ValueError(f"Roadmap engine produced {len(weeks)} weeks, expected 6")

        async with async_session() as session:
            await session.execute(
                update(Roadmap)
                .where(
                    Roadmap.user_id == uuid.UUID(user_id),
                    Roadmap.is_active == True,  # noqa: E712
                )
                .values(is_active=False)
            )

            new_roadmap = Roadmap(
                id=uuid.uuid4(),
                user_id=uuid.UUID(user_id),
                target_role=target_role,
                plan=roadmap_json,
                is_active=True,
                created_at=datetime.utcnow(),
            )
            session.add(new_roadmap)
            await session.commit()
            await session.refresh(new_roadmap)

        lines = [f"📅 Your 6-week roadmap for **{target_role}** (stack: {roadmap_json.get('primary_stack', '?')}):\n"]
        for w in weeks:
            topics_str = ", ".join(w.get("topics", []))
            lines.append(f"  Week {w['week']}: **{w['focus']}** — {topics_str}")
            if w.get("project_idea"):
                lines.append(f"    *Project*: {w['project_idea']}")

        return {
            **state,
            "structured_output": roadmap_json,
            "agent_output": "\n".join(lines),
            "error": None,
        }

    except Exception as exc:  # noqa: BLE001
        logger.exception("roadmap_agent_node failed: %s", exc)
        return {
            **state,
            "agent_output": ("Failed to generate roadmap. Run GitHub analysis first, then try again."),
            "error": str(exc),
        }
