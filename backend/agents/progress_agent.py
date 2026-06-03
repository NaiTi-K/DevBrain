"""
Progress Agent
==============
Computes analytics dynamically from database history: skill deltas, challenge pass
rate, exam readiness per topic, activity streak, daily activities, and weekly digest.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, date
from typing import Optional

from sqlalchemy import select

from models.database import async_session
from models import (
    User,
    ChallengeAttempt,
    CodeReview,
    InterviewSession,
    Roadmap,
    SkillProfile,
    ProgressSnapshot,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════ #
# Private helpers                                                             #
# ═══════════════════════════════════════════════════════════════════════════ #


def _nearest_snapshot(snapshots: list[ProgressSnapshot], target: datetime) -> Optional[ProgressSnapshot]:
    """Return the snapshot whose date is closest to (but not after) `target`."""
    target_date = target.date()
    candidates = [s for s in snapshots if s.snapshot_date <= target_date]
    return candidates[-1] if candidates else None


def _calculate_consecutive_streaks(active_dates: set[date]) -> tuple[int, int, date | None]:
    """
    Computes current streak, longest streak, and last activity date from a set of active dates.
    """
    if not active_dates:
        return 0, 0, None

    sorted_dates = sorted(list(active_dates))
    today = datetime.utcnow().date()
    yesterday = today - timedelta(days=1)

    # Longest streak
    longest = 0
    current_run = 0
    prev_date = None
    for d in sorted_dates:
        if prev_date is None:
            current_run = 1
        elif d == prev_date + timedelta(days=1):
            current_run += 1
        elif d > prev_date + timedelta(days=1):
            if current_run > longest:
                longest = current_run
            current_run = 1
        prev_date = d
    if current_run > longest:
        longest = current_run

    # Current streak (must end today or yesterday)
    current = 0
    last_act = sorted_dates[-1]
    if last_act >= yesterday:
        check = last_act
        while check in active_dates:
            current += 1
            check -= timedelta(days=1)

    return current, longest, last_act


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
                    skills_snapshot=data["skills"],
                    challenges_done=data["challenges_done"],
                    challenges_passed=data["challenges_passed"],
                )
            )
        await session.commit()


def _deterministic_digest(
    skill_delta_7d: list[dict],
    pass_rate: float,
    streak: int,
    exam_readiness: dict[str, int],
) -> str:
    """Fast, non-LLM digest summarizing progress."""
    improving = [d["skill"] for d in skill_delta_7d if d["delta_7d"] > 0.01]
    declining = [d["skill"] for d in skill_delta_7d if d["delta_7d"] < -0.01]
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


# ═══════════════════════════════════════════════════════════════════════════ #
# Agent node                                                                  #
# ═══════════════════════════════════════════════════════════════════════════ #


async def progress_agent_node(state: dict) -> dict:
    """
    LangGraph node: compute full progress analytics dynamically.
    """
    user_id: str = state["user_id"]

    try:
        now = datetime.utcnow()
        cutoff_30d = now - timedelta(days=30)
        cutoff_7d = now - timedelta(days=7)

        # ── 1. Fetch all relevant records from DB ─────────────────────────────
        async with async_session() as session:
            # Fetch User
            user_res = await session.execute(select(User).where(User.id == uuid.UUID(user_id)))
            user = user_res.scalar_one_or_none()
            if not user:
                raise ValueError(f"User {user_id} not found.")

            # Fetch SkillProfile
            sp_res = await session.execute(
                select(SkillProfile)
                .where(SkillProfile.user_id == uuid.UUID(user_id))
                .order_by(SkillProfile.analyzed_at.desc())
                .limit(1)
            )
            skill_profile = sp_res.scalar_one_or_none()

            # Fetch ChallengeAttempts
            attempts_res = await session.execute(
                select(ChallengeAttempt)
                .where(ChallengeAttempt.user_id == uuid.UUID(user_id))
                .order_by(ChallengeAttempt.attempted_at.asc())
            )
            attempts = list(attempts_res.scalars().all())

            # Fetch CodeReviews
            reviews_res = await session.execute(
                select(CodeReview).where(CodeReview.user_id == uuid.UUID(user_id)).order_by(CodeReview.created_at.asc())
            )
            reviews = list(reviews_res.scalars().all())

            # Fetch InterviewSessions
            interviews_res = await session.execute(
                select(InterviewSession)
                .where(InterviewSession.user_id == uuid.UUID(user_id))
                .order_by(InterviewSession.created_at.asc())
            )
            interviews = list(interviews_res.scalars().all())

            # Fetch active Roadmap
            roadmap_res = await session.execute(
                select(Roadmap)
                .where(Roadmap.user_id == uuid.UUID(user_id), Roadmap.is_active == True)  # noqa: E712
                .order_by(Roadmap.created_at.desc())
                .limit(1)
            )
            roadmap = roadmap_res.scalar_one_or_none()

            # Fetch all ProgressSnapshots (last 30 days)
            snapshots_res = await session.execute(
                select(ProgressSnapshot)
                .where(
                    ProgressSnapshot.user_id == uuid.UUID(user_id),
                    ProgressSnapshot.snapshot_date >= cutoff_30d.date(),
                )
                .order_by(ProgressSnapshot.snapshot_date.asc())
            )
            snapshots = list(snapshots_res.scalars().all())

        # ── 2. User Data ──────────────────────────────────────────────────────
        user_data = {
            "id": str(user.id),
            "github_id": user.github_id,
            "username": user.github_username,
            "email": None,
            "avatar_url": user.avatar_url,
            "name": user.display_name,
            "created_at": user.created_at.isoformat() if user.created_at else "",
            "updated_at": user.created_at.isoformat() if user.created_at else "",
        }

        # ── 3. Skill Profile ──────────────────────────────────────────────────
        skill_profile_data = None
        current_skills: dict[str, float] = {}
        if skill_profile:
            current_skills = skill_profile.skills or {}
            skill_profile_data = {
                "user_id": str(skill_profile.user_id),
                "github_username": user.github_username,
                "skills": current_skills,
                "summary": skill_profile.summary or "",
                "repo_count": skill_profile.repo_count or 0,
                "analyzed_at": skill_profile.analyzed_at,
            }

        # ── 4. Unified Activity Streak ────────────────────────────────────────
        active_dates = set()
        for att in attempts:
            active_dates.add(att.attempted_at.date())
        for rev in reviews:
            active_dates.add(rev.created_at.date())
        for iv in interviews:
            active_dates.add(iv.created_at.date())

        current_streak, longest_streak, last_act_date = _calculate_consecutive_streaks(active_dates)
        streak_data = {
            "current_streak": current_streak,
            "longest_streak": longest_streak,
            "last_activity_date": last_act_date,
        }

        # ── 5. Skill Deltas ───────────────────────────────────────────────────
        snap_7d = _nearest_snapshot(snapshots, cutoff_7d)
        skills_7d = snap_7d.skills if snap_7d else {}

        snap_30d = snapshots[0] if snapshots else None
        skills_30d = snap_30d.skills if snap_30d else {}

        skill_deltas = []
        for skill, current_score in current_skills.items():
            delta_7 = current_score - skills_7d.get(skill, 0.0)
            delta_30 = current_score - skills_30d.get(skill, 0.0)
            skill_deltas.append(
                {
                    "skill": skill,
                    "delta_7d": round(delta_7, 4),
                    "delta_30d": round(delta_30, 4),
                    "current_score": round(current_score, 4),
                }
            )

        # ── 6. Challenge Metrics & Pass Rate ──────────────────────────────────
        solved_challenge_ids = {att.challenge_id for att in attempts if att.passed}
        total_challenges_solved = len(solved_challenge_ids)
        total_reviews_submitted = len(reviews)
        total_interview_sessions = sum(1 for iv in interviews if (iv.score is not None or iv.completed))

        total_attempts = len(attempts)
        passed_attempts = sum(1 for att in attempts if att.passed)
        pass_rate = passed_attempts / total_attempts if total_attempts > 0 else 0.0

        start_of_week = (now - timedelta(days=now.weekday())).date()
        weekly_solved_ids = {
            att.challenge_id for att in attempts if att.passed and att.attempted_at.date() >= start_of_week
        }
        weekly_challenges_done = len(weekly_solved_ids)
        weekly_challenge_goal = 5

        # ── 7. Exam Readiness ─────────────────────────────────────────────────
        exam_readiness = {}
        for skill, score in current_skills.items():
            raw_score_component = int(score * 50)  # 0-50
            pass_rate_component = int(pass_rate * 30)  # 0-30
            recency_bonus = 20 if last_act_date and last_act_date >= cutoff_7d.date() else 0
            total = raw_score_component + pass_rate_component + recency_bonus
            exam_readiness[skill] = min(total, 100)

        exam_readiness_score = sum(exam_readiness.values()) / (100.0 * len(exam_readiness)) if exam_readiness else 0.0

        # ── 8. Daily Activity (last 30 days) ──────────────────────────────────
        daily_activity = []
        for i in range(30):
            d = (now - timedelta(days=29 - i)).date()
            challenges_solved_d = sum(1 for att in attempts if att.passed and att.attempted_at.date() == d)
            reviews_submitted_d = sum(1 for rev in reviews if rev.created_at.date() == d)
            interview_sessions_d = sum(1 for iv in interviews if iv.created_at.date() == d)
            total_activity_d = challenges_solved_d + reviews_submitted_d + interview_sessions_d

            daily_activity.append(
                {
                    "date": d.isoformat(),
                    "challenges_solved": challenges_solved_d,
                    "reviews_submitted": reviews_submitted_d,
                    "interview_sessions": interview_sessions_d,
                    "total_activity": total_activity_d,
                }
            )

        # ── 9. Skill Trend Data ───────────────────────────────────────────────
        trend_data = []
        for s in snapshots:
            snap_date = s.snapshot_date
            avg_score = sum(s.skills.values()) / len(s.skills) if s.skills else 0.0
            trend_data.append(
                {
                    "date": snap_date.isoformat(),
                    "score": round(avg_score * 100.0, 2),
                }
            )

        if not trend_data and current_skills:
            avg_score = sum(current_skills.values()) / len(current_skills)
            trend_data.append(
                {
                    "date": now.date().isoformat(),
                    "score": round(avg_score * 100.0, 2),
                }
            )

        # ── 10. Roadmap Tracker ───────────────────────────────────────────────
        roadmap_tracker = None
        if roadmap:
            weeks = roadmap.plan.get("weeks", [])
            total_topics = sum(len(w.get("topics", [])) for w in weeks)
            completed_topics = sum(len(w.get("completed_topics", [])) for w in weeks)
            completed_weeks = sum(1 for w in weeks if w.get("completed") is True)
            percent_completed = completed_topics / total_topics if total_topics > 0 else 0.0
            roadmap_tracker = {
                "id": str(roadmap.id),
                "target_role": roadmap.target_role,
                "total_weeks": len(weeks),
                "completed_weeks": completed_weeks,
                "percent_completed": percent_completed,
                "total_topics": total_topics,
                "completed_topics": completed_topics,
            }

        # ── 11. Upsert today's snapshot ───────────────────────────────────────
        today_snapshot_data = {
            "skills": current_skills,
            "challenges_done": sum(1 for att in attempts if att.attempted_at.date() == now.date()),
            "challenges_passed": sum(1 for att in attempts if att.passed and att.attempted_at.date() == now.date()),
        }
        await _upsert_snapshot(user_id=user_id, now=now, data=today_snapshot_data)

        # ── 12. Weekly Digest ─────────────────────────────────────────────────
        weekly_digest = _deterministic_digest(
            skill_delta_7d=skill_deltas,
            pass_rate=pass_rate,
            streak=current_streak,
            exam_readiness=exam_readiness,
        )

        # ── 13. Build final output ────────────────────────────────────────────
        structured = {
            "user": user_data,
            "streak": streak_data,
            "skill_profile": skill_profile_data,
            "skill_deltas": skill_deltas,
            "total_challenges_solved": total_challenges_solved,
            "total_reviews_submitted": total_reviews_submitted,
            "total_interview_sessions": total_interview_sessions,
            "exam_readiness_score": exam_readiness_score,
            "exam_readiness": exam_readiness,
            "weekly_digest": weekly_digest,
            "daily_activity": daily_activity,
            "trend_data": trend_data,
            "weekly_challenge_goal": weekly_challenge_goal,
            "weekly_challenges_done": weekly_challenges_done,
            "roadmap_tracker": roadmap_tracker,
            # Backward-compatible fields
            "skill_delta_7d": {d["skill"]: d["delta_7d"] for d in skill_deltas},
            "skill_delta_30d": {d["skill"]: d["delta_30d"] for d in skill_deltas},
            "challenge_pass_rate": pass_rate,
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
