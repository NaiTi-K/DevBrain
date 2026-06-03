"""
GitHub Analyzer Agent
=====================
Pipeline:
  1. github_service  → raw repo/skill data (deterministic)
  2. profile_engine  → structured analysis report + Markdown (deterministic)
  3. LLM (optional)  → prose polish only; facts come from step 2

Cross-file contracts (DO NOT CHANGE):
  - SkillProfileResponse  ← imported by route files
  - github_analyzer_node  ← registered as a LangGraph node
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import select

from core.config import settings
from models.database import async_session
from models.skill_profile import SkillProfile
from services.cache_service import cache
from services.github_service import github_service
from services.llm_service import GroqRateLimitError, llm
from services.profile_engine import build_analysis_report, render_analysis_markdown

logger = logging.getLogger(__name__)


async def _maybe_enhance_with_llm(base_summary: str, analysis_report: dict) -> str:
    """
    Optional LLM polish — receives the deterministic report as ground truth.
    On any failure, returns base_summary unchanged.
    """
    username = analysis_report["github_username"]
    gaps = analysis_report.get("gaps", [])[:4]
    repos = [r.get("name") for r in analysis_report.get("repo_highlights", [])[:5]]
    gap_lines = "\n".join(f"- {g['title']}: {g['action']}" for g in gaps)

    prompt = (
        f"Rewrite this GitHub portfolio review for @{username} to be sharper and more direct. "
        f"Do NOT invent facts. Do NOT change numbers. Keep the same four Markdown headers.\n\n"
        f"Repos you MUST mention: {', '.join(repos) or 'none'}\n"
        f"Gaps you MUST address:\n{gap_lines}\n\n"
        f"BASE REPORT:\n{base_summary}"
    )
    system = (
        "You polish technical portfolio reviews. Every claim must come from the base report. "
        "Cite repo names. No generic encouragement."
    )
    try:
        enhanced = await llm.call(
            prompt,
            system=system,
            max_tokens=1400,
            temperature=0.3,
            max_retries=2,
            try_fallback=True,
        )
        if enhanced and len(enhanced.strip()) > 200:
            return enhanced.strip()
    except GroqRateLimitError as exc:
        logger.info("LLM polish skipped for %s (rate limit ~%ds)", username, int(exc.retry_after))
    except Exception as exc:
        logger.warning("LLM polish failed for %s: %s", username, exc)

    return base_summary


class SkillProfileResponse(BaseModel):
    user_id: str
    github_username: str
    skills: dict[str, float]
    summary: str
    repo_count: int
    analyzed_at: datetime

    class Config:
        from_attributes = True


async def github_analyzer_node(state: dict) -> dict:
    """
    LangGraph node: analyse GitHub repos → structured profile + narrative.

    Flow
    ----
    1. Cache lookup (skipped on force_refresh).
    2. github_service.analyze_skill_profile()
    3. profile_engine.build_analysis_report() + render_analysis_markdown()
    4. Optional LLM prose polish.
    5. Redis + PostgreSQL write-through.
    """
    user_id: str = state["user_id"]
    github_username: str = state["github_username"]

    try:
        force_refresh: bool = bool(state.get("force_refresh", False))
        analysis_report: dict = {}

        if force_refresh:
            await cache.delete_skill_profile(user_id)
            await cache.delete_progress_dashboard(user_id)
            cached = None
        else:
            cached = await cache.get_skill_profile(user_id)

        if cached:
            logger.info("Cache hit — skill profile user_id=%s", user_id)
            skills = cached.get("skills", {})
            repo_count = cached.get("repo_count", 0)
            summary = cached.get("summary", "")
            frameworks = cached.get("frameworks", {})
            ep = cached.get("engineering_practices", {})
            repo_highlights = cached.get("repo_highlights", [])
            sample_commits = cached.get("sample_commits", [])
            analysis_report = cached.get("analysis_report", {})
        else:
            token: Optional[str] = None
            raw_input: str = state.get("user_input", "")
            if raw_input.startswith("ghp_") or raw_input.startswith("github_pat_"):
                token = raw_input.strip()
            else:
                token = settings.GITHUB_PAT or None

            profile_data = await github_service.analyze_skill_profile(github_username, token)

            # ── Deterministic pipeline (core logic) ────────────────────────
            analysis_report = build_analysis_report(profile_data, github_username)
            base_summary = render_analysis_markdown(analysis_report)

            skills = analysis_report["skills"]
            repo_count = analysis_report["repo_count"]
            frameworks = analysis_report["frameworks"]
            ep = analysis_report["engineering_practices"]
            repo_highlights = analysis_report["repo_highlights"]
            sample_commits = analysis_report["sample_commits"]

            # ── Optional LLM polish (never required) ───────────────────────
            summary = await _maybe_enhance_with_llm(base_summary, analysis_report)

            await cache.set_skill_profile(
                user_id,
                {
                    "skills": skills,
                    "repo_count": repo_count,
                    "summary": summary,
                    "frameworks": frameworks,
                    "engineering_practices": ep,
                    "repo_highlights": repo_highlights,
                    "sample_commits": sample_commits,
                    "analysis_report": analysis_report,
                    "github_username": github_username,
                    "repo_rankings": profile_data.get("repo_rankings", []),
                    "deep_scanned_names": profile_data.get("deep_scanned_names", []),
                },
            )

        # Rebuild analysis_report from cache if missing (legacy entries)
        if not analysis_report and skills:
            analysis_report = build_analysis_report(
                {
                    "skills": skills,
                    "frameworks": frameworks,
                    "engineering_practices": ep,
                    "repo_highlights": repo_highlights,
                    "sample_commits": sample_commits,
                    "repo_count": repo_count,
                },
                github_username,
            )

        async with async_session() as session:
            result = await session.execute(select(SkillProfile).where(SkillProfile.user_id == uuid.UUID(user_id)))
            existing = result.scalar_one_or_none()
            now = datetime.utcnow()

            if existing:
                existing.skills = skills
                existing.repo_count = repo_count
                existing.summary = summary
                existing.analyzed_at = now
            else:
                session.add(
                    SkillProfile(
                        id=uuid.uuid4(),
                        user_id=uuid.UUID(user_id),
                        github_username=github_username,
                        skills=skills,
                        repo_count=repo_count,
                        summary=summary,
                        analyzed_at=now,
                    )
                )
            await session.commit()

        structured = {
            "skills": skills,
            "summary": summary,
            "repo_count": repo_count,
            "frameworks": frameworks,
            "engineering_practices": ep,
            "repo_highlights": repo_highlights,
            "sample_commits": sample_commits,
            "analysis_report": analysis_report,
        }

        return {
            **state,
            "skill_profile": {
                "skills": skills,
                "frameworks": frameworks,
                "analysis_report": analysis_report,
                "engineering_practices": ep,
                "repo_highlights": repo_highlights,
            },
            "structured_output": structured,
            "agent_output": summary,
            "error": None,
        }

    except Exception as exc:  # noqa: BLE001
        logger.exception("github_analyzer_node failed for user_id=%s: %s", user_id, exc)
        return {
            **state,
            "agent_output": "Failed to analyse GitHub profile. Please try again later.",
            "error": str(exc),
        }
