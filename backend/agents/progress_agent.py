"""
Progress Agent
==============
Computes analytics from ProgressSnapshot history: skill deltas, challenge pass
rate, exam readiness per topic, activity streak, and a Grok-generated weekly
digest.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select

from models.database import async_session
from models.progress import ProgressSnapshot
from services.cache_service import cache

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════ #
# Agent node                                                                  #
# ═══════════════════════════════════════════════════════════════════════════ #


async def progress_agent_node(state: dict) -> dict:
    """
    LangGraph node: compute full progress analytics for the user.

    Steps
    -----
    1. Load ProgressSnapshots for the last 30 days.
    2. Load current skill profile from cache or DB.
    3. Compute skill deltas (7 d & 30 d), challenge pass rate, streak,
       and exam readiness per topic.
    4. Upsert today's ProgressSnapshot.
    5. Ask Grok for a 3-sentence weekly digest.
    6. Populate state fields.
    """
    user_id: str = state["user_id"]

    try:
        now = datetime.utcnow()
        cutoff_30d = now - timedelta(days=30)
        cutoff_7d = now - timedelta(days=7)

        # ── 1. Load snapshots from DB ──────────────────────────────────────
        async with async_session() as session:
            rows = await session.execute(
                select(ProgressSnapshot)
                .where(
                    ProgressSnapshot.user_id == uuid.UUID(user_id),
                    ProgressSnapshot.snapshot_date >= cutoff_30d.date(),
                )
                .order_by(ProgressSnapshot.snapshot_date.asc())
            )
            snapshots: list[ProgressSnapshot] = list(rows.scalars().all())

        # ── 2. Resolve current skill profile ──────────────────────────────
        skill_profile: dict = state.get("skill_profile") or {}
        current_skills: dict[str, float] = skill_profile.get("skills", {})

        if not current_skills:
            cached = await cache.get_skill_profile(user_id)
            if cached:
                current_skills = cached.get("skills", {})

        # ── 3a. Skill deltas ───────────────────────────────────────────────
        skill_delta_7d: dict[str, float] = {}
        skill_delta_30d: dict[str, float] = {}

        snapshot_7d_ago = _nearest_snapshot(snapshots, cutoff_7d)
        snapshot_30d_ago = snapshots[0] if snapshots else None

        if snapshot_7d_ago and snapshot_7d_ago.skills:
            old_7 = snapshot_7d_ago.skills
            skill_delta_7d = {
                k: round(current_skills.get(k, 0.0) - old_7.get(k, 0.0), 4)
                for k in set(current_skills) | set(old_7)
            }

        if snapshot_30d_ago and snapshot_30d_ago.skills:
            old_30 = snapshot_30d_ago.skills
            skill_delta_30d = {
                k: round(current_skills.get(k, 0.0) - old_30.get(k, 0.0), 4)
                for k in set(current_skills) | set(old_30)
            }

        # ── 3b. Challenge pass rate ────────────────────────────────────────
        total_done = sum(s.challenges_done for s in snapshots)
        total_passed = sum(s.challenges_passed for s in snapshots)
        pass_rate: float = round(total_passed / total_done, 4) if total_done else 0.0

        # ── 3c. Streak (consecutive days with ≥ 1 challenge) ──────────────
        streak: int = _compute_streak(snapshots, now)

        # ── 3d. Exam readiness per topic (0-100) ──────────────────────────
        exam_readiness: dict[str, int] = _compute_exam_readiness(
            snapshots=snapshots,
            current_skills=current_skills,
            pass_rate=pass_rate,
        )

        # ── 4. Upsert today's ProgressSnapshot ────────────────────────────
        today_snapshot_data = {
            "skills": current_skills,
            "challenges_done": _today_challenges_done(snapshots, now),
            "challenges_passed": _today_challenges_passed(snapshots, now),
        }
        await _upsert_snapshot(user_id=user_id, now=now, data=today_snapshot_data)

        # ── 5. Weekly digest (deterministic only — never competes with GitHub analyze)
        weekly_digest: str = _deterministic_digest(
            skill_delta_7d=skill_delta_7d,
            pass_rate=pass_rate,
            streak=streak,
            exam_readiness=exam_readiness,
        )

        # ── 6. Build output ────────────────────────────────────────────────
        structured: dict = {
            "skill_delta_7d": skill_delta_7d,
            "skill_delta_30d": skill_delta_30d,
            "streak": streak,
            "exam_readiness": exam_readiness,
            "challenge_pass_rate": pass_rate,
            "weekly_digest": weekly_digest,
        }

        return {
            **state,
            "structured_output": structured,
            "agent_output": weekly_digest,
            "error": None,
        }

    except Exception as exc:  # noqa: BLE001
        logger.exception("progress_agent_node failed: %s", exc)
        return {
            **state,
            "agent_output": "Unable to compute progress data. Please try again.",
            "error": str(exc),
        }


# ═══════════════════════════════════════════════════════════════════════════ #
# Private helpers                                                             #
# ═══════════════════════════════════════════════════════════════════════════ #


def _nearest_snapshot(
    snapshots: list[ProgressSnapshot], target: datetime
) -> Optional[ProgressSnapshot]:
    """Return the snapshot whose date is closest to (but not after) `target`."""
    target_date = target.date()
    candidates = [s for s in snapshots if s.snapshot_date <= target_date]
    return candidates[-1] if candidates else None


def _compute_streak(snapshots: list[ProgressSnapshot], now: datetime) -> int:
    """
    Count the number of consecutive days ending today (or yesterday) where
    challenges_done > 0 and greater than the day before.
    """
    if not snapshots:
        return 0

    # Build a date → snapshot map for quick lookup
    by_date = {s.snapshot_date: s for s in snapshots}
    streak = 0
    check_date = now.date()

    while True:
        snap = by_date.get(check_date)
        if snap and snap.challenges_done > 0:
            streak += 1
            check_date -= timedelta(days=1)
        else:
            break

    return streak


def _compute_exam_readiness(
    snapshots: list[ProgressSnapshot],
    current_skills: dict[str, float],
    pass_rate: float,
) -> dict[str, int]:
    """
    Heuristic exam readiness score per skill topic (0-100).
    Formula: 50% raw skill score + 30% pass rate contribution + 20% recency bonus.
    """
    readiness: dict[str, int] = {}
    recent_cutoff = (datetime.utcnow() - timedelta(days=7)).date()
    has_recent_activity = any(s.snapshot_date >= recent_cutoff for s in snapshots)
    recency_bonus = 20 if has_recent_activity else 0

    for skill, score in current_skills.items():
        raw_score_component = int(score * 50)          # 0-50
        pass_rate_component = int(pass_rate * 30)      # 0-30
        total = raw_score_component + pass_rate_component + recency_bonus
        readiness[skill] = min(total, 100)

    return readiness


def _today_challenges_done(snapshots: list[ProgressSnapshot], now: datetime) -> int:
    today = now.date()
    snap = next((s for s in snapshots if s.snapshot_date == today), None)
    return snap.challenges_done if snap else 0


def _today_challenges_passed(snapshots: list[ProgressSnapshot], now: datetime) -> int:
    today = now.date()
    snap = next((s for s in snapshots if s.snapshot_date == today), None)
    return snap.challenges_passed if snap else 0


async def _upsert_snapshot(user_id: str, now: datetime, data: dict) -> None:
    """Insert or update today's ProgressSnapshot."""
    today = now.date()
    async with async_session() as session:
        result = await session.execute(
            select(ProgressSnapshot).where(
                ProgressSnapshot.user_id == uuid.UUID(user_id),
                ProgressSnapshot.snapshot_date == today,
            )
        )
        existing: Optional[ProgressSnapshot] = result.scalar_one_or_none()
        if existing:
            existing.skills = data["skills"]
            existing.challenges_done = data["challenges_done"]
            existing.challenges_passed = data["challenges_passed"]
        else:
            session.add(
                ProgressSnapshot(
                    id=uuid.uuid4(),
                    user_id=uuid.UUID(user_id),
                    snapshot_date=today,
                    skills=data["skills"],
                    challenges_done=data["challenges_done"],
                    challenges_passed=data["challenges_passed"],
                )
            )
        await session.commit()


def _deterministic_digest(
    skill_delta_7d: dict[str, float],
    pass_rate: float,
    streak: int,
    exam_readiness: dict[str, int],
) -> str:
    """Fast, non-LLM digest so dashboard loads never compete with GitHub analysis."""
    improving = [k for k, v in skill_delta_7d.items() if v > 0.01]
    declining = [k for k, v in skill_delta_7d.items() if v < -0.01]
    top_ready = sorted(exam_readiness.items(), key=lambda x: x[1], reverse=True)[:3]
    top_ready_str = ", ".join(f"{k} ({v}%)" for k, v in top_ready) or "run GitHub analysis first"

    return (
        f"#### Progress & Wins\n"
        f"- Activity streak: **{streak}** day(s)\n"
        f"- Challenge pass rate: **{pass_rate * 100:.0f}%**\n"
        f"- Improving skills: {', '.join(improving) or 'none yet — complete challenges to track growth'}\n\n"
        f"#### Areas for Improvement\n"
        f"- Needs attention: {', '.join(declining) or 'no declining skills detected'}\n"
        f"- Exam readiness leaders: {top_ready_str}\n\n"
        f"#### Action Plan\n"
        f"- Complete 2–3 coding challenges this week to build your streak.\n"
        f"- Focus practice on your lowest exam-readiness topic.\n"
        f"- Re-analyze GitHub after shipping new repos to refresh your roadmap."
    )


def _build_digest_prompt(
    skill_delta_7d: dict[str, float],
    pass_rate: float,
    streak: int,
    exam_readiness: dict[str, int],
) -> str:
    improving = [k for k, v in skill_delta_7d.items() if v > 0]
    declining = [k for k, v in skill_delta_7d.items() if v < 0]

    top_ready = sorted(exam_readiness.items(), key=lambda x: x[1], reverse=True)[:3]
    top_ready_str = ", ".join(f"{k} ({v}%)" for k, v in top_ready) or "N/A"

    return (
        f"You are an encouraging engineering career coach writing a weekly progress digest.\n\n"
        f"Stats this week:\n"
        f"  - Current activity streak : {streak} day(s)\n"
        f"  - Challenge pass rate      : {pass_rate * 100:.1f}%\n"
        f"  - Improving skills         : {', '.join(improving) or 'none'}\n"
        f"  - Declining/stagnant skills: {', '.join(declining) or 'none'}\n"
        f"  - Top exam-ready topics    : {top_ready_str}\n\n"
        f"Write a comprehensive markdown-formatted weekly progress digest. You MUST include these three exact headers:\n"
        f"#### Progress & Wins\n"
        f"Celebrate their progress, highlighting specific improving skills and their current streak/pass rate.\n\n"
        f"#### Areas for Improvement\n"
        f"Highlight the most important areas that still need work based on declining or stagnant skills.\n\n"
        f"#### Action Plan\n"
        f"Give concrete actions for the coming week to maintain momentum and tackle weak areas.\n\n"
        f"Be warm, motivational, and highly specific to the provided stats."
    )
