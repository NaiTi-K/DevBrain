# Replace the stub in main.py with: from api.routes.challenges import router as challenges_router

"""
Challenge Routes
================
POST  /challenges/generate              — generate an adaptive challenge
POST  /challenges/{challenge_id}/submit — submit code and get evaluation + feedback
GET   /challenges/history               — last 20 attempts with challenge details
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select

from agents.challenge_agent import challenge_agent_node
from services.sandbox_service import run_code
import asyncio
import json
from core.dependencies import get_current_user, get_db
from models.challenge import Challenge, ChallengeAttempt
from models.user import User
from services.cache_service import cache
from services.llm_service import llm

logger = logging.getLogger(__name__)

router = APIRouter(tags=["challenges"])

# ── Response schemas ──────────────────────────────────────────────────────


class ChallengeResponse(BaseModel):
    id: str
    title: str
    description: str
    difficulty: str
    language: str
    topic: str
    constraints: list[str] = []
    examples: list[dict] = []
    mcqs: list[dict] = []
    starter_codes: dict[str, str] = {}
    test_cases: list[dict] = []
    # Note: solution is intentionally omitted from the response

    class Config:
        from_attributes = True


class SubmitRequest(BaseModel):
    code: str
    mcq_answers: list[int] = []
    language: str = "python"


class AttemptResult(BaseModel):
    attempt_id: str
    challenge_id: str
    tests_passed: int
    tests_total: int
    mcqs_passed: int = 0
    passed: bool
    output: str
    error: Optional[str]
    feedback: str  # Grok explanation
    suggest_more_practice: bool = False
    topic: Optional[str] = None


class AttemptHistoryItem(BaseModel):
    attempt_id: str
    challenge_id: str
    challenge_title: str
    challenge_topic: str
    difficulty: str
    language: str
    passed: bool
    tests_passed: int
    tests_total: int
    mcqs_passed: int = 0
    submitted_at: datetime


# ══════════════════════════════════════════════════════════════════════════ #
# POST /challenges/generate                                                  #
# ══════════════════════════════════════════════════════════════════════════ #


@router.post(
    "/generate",
    response_model=ChallengeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate an adaptive coding challenge targeting the user's weakest skill",
)
async def generate_challenge(
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Runs the challenge agent to produce a tailored problem based on the user's
    skill profile stored in Redis/PostgreSQL.
    """
    user_id = str(current_user.id)

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    result = await db.execute(
        select(Challenge)
        .where(Challenge.user_id == current_user.id, Challenge.created_at >= today_start)
        .order_by(Challenge.created_at.desc())
    )
    existing_challenge = result.scalars().first()
    if existing_challenge:
        return ChallengeResponse(
            id=str(existing_challenge.id),
            title=existing_challenge.title,
            description=existing_challenge.description,
            difficulty=existing_challenge.difficulty,
            topic=existing_challenge.topic,
            language=existing_challenge.language,
            constraints=existing_challenge.constraints or [],
            examples=existing_challenge.examples or [],
            mcqs=existing_challenge.mcqs or [],
            starter_codes=existing_challenge.starter_codes or {},
            test_cases=existing_challenge.test_cases or [],
        )

    skill_profile: dict = {}
    cached = await cache.get_skill_profile(user_id)
    if cached:
        skill_profile = {"skills": cached.get("skills", {})}

    state = {
        "user_id": user_id,
        "github_username": current_user.github_username or "",
        "intent": "challenge",
        "current_agent": "challenge_agent",
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

    final_state = await challenge_agent_node(state)

    if final_state.get("error"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Challenge generation failed: {final_state['error']}",
        )

    structured = final_state.get("structured_output", {})
    challenge_id = structured.get("id")
    if not challenge_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Challenge was generated but could not be retrieved.",
        )

    result = await db.execute(select(Challenge).where(Challenge.id == uuid.UUID(challenge_id)))
    challenge: Optional[Challenge] = result.scalar_one_or_none()

    if not challenge:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Challenge not found after creation."
        )

    return ChallengeResponse(
        id=str(challenge.id),
        title=challenge.title,
        description=challenge.description,
        difficulty=challenge.difficulty,
        topic=challenge.topic,
        language=challenge.language,
        constraints=challenge.constraints or [],
        examples=challenge.examples or [],
        mcqs=challenge.mcqs or [],
        starter_codes=challenge.starter_codes or {},
        test_cases=challenge.test_cases or [],
    )


# ══════════════════════════════════════════════════════════════════════════ #
# POST /challenges/{challenge_id}/submit                                     #
# ══════════════════════════════════════════════════════════════════════════ #


@router.post(
    "/{challenge_id}/submit",
    response_model=AttemptResult,
    status_code=status.HTTP_200_OK,
    summary="Submit code for a challenge and receive evaluation + AI feedback",
)
async def submit_challenge(
    challenge_id: str,
    body: SubmitRequest,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Evaluates `code` against the challenge's test cases in a sandboxed
    subprocess (5 s timeout per test).  Records a `ChallengeAttempt`.

    If the user has failed the **same topic 3+ times**, the response includes:
    `{"suggest_more_practice": true, "topic": "..."}`.

    Also returns `feedback` — a Grok explanation of the solution and tips.
    """
    try:
        cid = uuid.UUID(challenge_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="challenge_id must be a valid UUID.",
        )

    # Fetch challenge
    result = await db.execute(select(Challenge).where(Challenge.id == cid))
    challenge: Optional[Challenge] = result.scalar_one_or_none()
    if not challenge:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Challenge not found.")

    # ── Run sandboxed evaluation ──────────────────────────────────────────
    # Note: If challenge.schema is missing on old challenges, fallback to default schema
    schema = challenge.schema or {"params": [], "returns": "int"}
    eval_result = await asyncio.to_thread(
        run_code, body.language, body.code, schema, challenge.test_cases, challenge.judge
    )

    tests_total = len(eval_result["test_results"])
    tests_passed = sum(1 for tr in eval_result["test_results"] if tr["status"] == "AC")
    passed = eval_result["status"] == "AC"

    # ── Evaluate MCQs ─────────────────────────────────────────────────────
    mcqs_passed = 0
    if challenge.mcqs and body.mcq_answers:
        for i, mcq in enumerate(challenge.mcqs):
            if i < len(body.mcq_answers) and body.mcq_answers[i] == mcq.get("correct_index", -1):
                mcqs_passed += 1

    # ── Save attempt ──────────────────────────────────────────────────────
    # Avoid duplicating rows: Update existing attempt for this challenge by this user today
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    result = await db.execute(
        select(ChallengeAttempt)
        .where(
            ChallengeAttempt.challenge_id == cid,
            ChallengeAttempt.user_id == current_user.id,
            ChallengeAttempt.attempted_at >= today_start,
        )
        .order_by(ChallengeAttempt.attempted_at.desc())
    )
    existing_attempt = result.scalars().first()

    if existing_attempt:
        existing_attempt.submitted_code = body.code
        existing_attempt.language = body.language
        existing_attempt.output = json.dumps(eval_result)
        existing_attempt.tests_passed = tests_passed
        existing_attempt.tests_total = tests_total
        # Only overwrite MCQ score if they actually answered MCQs in this step
        if body.mcq_answers:
            existing_attempt.mcqs_passed = mcqs_passed
        existing_attempt.passed = passed
        existing_attempt.submitted_at = datetime.now(timezone.utc)
        attempt = existing_attempt
    else:
        attempt = ChallengeAttempt(
            id=uuid.uuid4(),
            user_id=current_user.id,
            challenge_id=cid,
            submitted_code=body.code,
            language=body.language,
            output=json.dumps(eval_result),
            tests_passed=tests_passed,
            tests_total=tests_total,
            mcqs_passed=mcqs_passed,
            passed=passed,
            submitted_at=datetime.now(timezone.utc),
        )
        db.add(attempt)

    await db.commit()
    await db.refresh(attempt)
    await cache.delete_progress_dashboard(str(current_user.id))

    # ── Check if user needs more practice on this topic ───────────────────
    suggest_more_practice = False
    if not passed:
        # Count failures on the same topic
        fail_count_result = await db.execute(
            select(func.count(ChallengeAttempt.id))
            .join(Challenge, ChallengeAttempt.challenge_id == Challenge.id)
            .where(
                ChallengeAttempt.user_id == current_user.id,
                Challenge.topic == challenge.topic,
                ChallengeAttempt.passed == False,  # noqa: E712
            )
        )
        fail_count: int = fail_count_result.scalar_one() or 0
        if fail_count >= 3:
            suggest_more_practice = True

    # ── Ask Grok for solution explanation and tips ────────────────────────
    feedback_prompt = (
        f"A developer submitted code for a '{challenge.difficulty}' challenge titled "
        f"'{challenge.title}' (topic: {challenge.topic}).\n\n"
        f"Their code:\n```python\n{body.code}\n```\n\n"
        f"Test result: {tests_passed}/{tests_total} tests passed.\n\n"
        f"Reference solution:\n```python\n{challenge.solution or 'N/A'}\n```\n\n"
        f"Write exactly 3 paragraphs:\n"
        f"1. Explain what the correct approach is and why.\n"
        f"2. Point out what the developer did right and where they went wrong.\n"
        f"3. Give 2 concrete tips to improve their code quality for this topic.\n"
        f"Be specific, educational, and encouraging."
    )
    try:
        feedback: str = await llm.call(feedback_prompt)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Grok feedback generation failed: %s", exc)
        feedback = "Feedback unavailable right now. Review the reference solution above."

    return AttemptResult(
        attempt_id=str(attempt.id),
        challenge_id=challenge_id,
        tests_passed=tests_passed,
        tests_total=tests_total,
        mcqs_passed=mcqs_passed,
        passed=passed,
        output=json.dumps(eval_result),
        error=eval_result.get("stderr"),
        feedback=feedback,
        suggest_more_practice=suggest_more_practice,
        topic=challenge.topic if suggest_more_practice else None,
    )


# ══════════════════════════════════════════════════════════════════════════ #
# GET /challenges/history                                                    #
# ══════════════════════════════════════════════════════════════════════════ #


@router.get(
    "/history",
    response_model=list[AttemptHistoryItem],
    status_code=status.HTTP_200_OK,
    summary="Return the last 20 challenge attempts with challenge details",
)
async def challenge_history(
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Returns the 20 most recent `ChallengeAttempt` records for the current user,
    joined with the parent `Challenge` for title, topic, and difficulty.
    """
    rows = await db.execute(
        select(ChallengeAttempt, Challenge)
        .join(Challenge, ChallengeAttempt.challenge_id == Challenge.id)
        .where(ChallengeAttempt.user_id == current_user.id)
        .order_by(ChallengeAttempt.attempted_at.desc())
        .limit(20)
    )

    items: list[AttemptHistoryItem] = []
    for attempt, challenge in rows.all():
        items.append(
            AttemptHistoryItem(
                attempt_id=str(attempt.id),
                challenge_id=str(attempt.challenge_id),
                challenge_title=challenge.title,
                challenge_topic=challenge.topic,
                difficulty=challenge.difficulty,
                language=attempt.language,
                passed=attempt.passed,
                tests_passed=attempt.tests_passed,
                tests_total=attempt.tests_total,
                mcqs_passed=attempt.mcqs_passed,
                submitted_at=attempt.attempted_at,
            )
        )

    return items


# ── GET /challenges/attempts/{attempt_id} ──────────────────────────────────────


class AttemptDetailsResponse(BaseModel):
    attempt_id: str
    challenge_id: str
    challenge_title: str
    challenge_description: str
    challenge_difficulty: str
    challenge_topic: str
    code: str
    language: str
    passed: bool
    tests_passed: int
    tests_total: int
    mcqs_passed: int
    output: Optional[str]
    error: Optional[str]
    feedback: Optional[str]
    submitted_at: datetime
    test_cases: list
    mcqs: Optional[list] = None

    class Config:
        from_attributes = True


@router.get(
    "/attempts/{attempt_id}",
    response_model=AttemptDetailsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get complete details of a past challenge attempt",
)
async def get_attempt_details(
    attempt_id: str,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    try:
        aid = uuid.UUID(attempt_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="attempt_id must be a valid UUID.",
        )

    result = await db.execute(
        select(ChallengeAttempt, Challenge)
        .join(Challenge, ChallengeAttempt.challenge_id == Challenge.id)
        .where(ChallengeAttempt.id == aid, ChallengeAttempt.user_id == current_user.id)
    )
    row = result.first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attempt not found or unauthorized.",
        )

    attempt, challenge = row

    # Try parsing eval output to extract stderr
    stderr = None
    if attempt.output:
        try:
            eval_data = json.loads(attempt.output)
            stderr = eval_data.get("stderr")
        except Exception:
            pass

    return AttemptDetailsResponse(
        attempt_id=str(attempt.id),
        challenge_id=str(attempt.challenge_id),
        challenge_title=challenge.title,
        challenge_description=challenge.description,
        challenge_difficulty=challenge.difficulty,
        challenge_topic=challenge.topic,
        code=attempt.code,
        language=attempt.language,
        passed=attempt.passed,
        tests_passed=attempt.tests_passed,
        tests_total=attempt.tests_total,
        mcqs_passed=attempt.mcqs_passed,
        output=attempt.output,
        error=stderr,
        feedback=attempt.feedback,
        submitted_at=attempt.attempted_at,
        test_cases=challenge.test_cases or [],
        mcqs=challenge.mcqs or [],
    )
