"""
backend/models/challenge.py
AI-generated coding challenges and the user attempts against them.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from models.database import Base


class Challenge(Base):
    """A single coding challenge generated for (or shared by) a user."""

    __tablename__ = "challenges"

    # ── Primary key ──────────────────────────────────────────────────────────
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )

    # ── Ownership ─────────────────────────────────────────────────────────────
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Challenge specification ────────────────────────────────────────────────
    topic: Mapped[str] = mapped_column(String(100), nullable=False)
    # "Python" | "JavaScript" | "C++"
    language: Mapped[str] = mapped_column(String(20), nullable=False, default="Python")
    # "easy" | "medium" | "hard"
    difficulty: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # ── Test cases ────────────────────────────────────────────────────────────
    # Example:
    # [{"input": [2, 7, 11, 15], "target": 9, "expected": [0, 1]}, ...]
    test_cases: Mapped[list] = mapped_column(JSONB, nullable=False)

    constraints: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    examples: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    mcqs: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    starter_codes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # ── Reference solution (nullable — not always revealed) ───────────────────
    solution: Mapped[str | None] = mapped_column(Text, nullable=True)
    starter_code: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # ── Schema and Judgement ──────────────────────────────────────────────────
    schema: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    judge: Mapped[str] = mapped_column(String(50), nullable=False, default="exact")

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    user: Mapped["User"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "User",
        back_populates="challenges",
    )
    attempts: Mapped[list["ChallengeAttempt"]] = relationship(
        "ChallengeAttempt",
        back_populates="challenge",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<Challenge id={self.id} title={self.title!r} difficulty={self.difficulty}>"


class ChallengeAttempt(Base):
    """Records one user submission against a :class:`Challenge`."""

    __tablename__ = "challenge_attempts"

    # ── Primary key ──────────────────────────────────────────────────────────
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )

    # ── Foreign keys ──────────────────────────────────────────────────────────
    challenge_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("challenges.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Submission data ───────────────────────────────────────────────────────
    code: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(20), nullable=False, default="python")
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    passed: Mapped[bool] = mapped_column(nullable=False)
    tests_passed: Mapped[int] = mapped_column(Integer, nullable=False)
    tests_total: Mapped[int] = mapped_column(Integer, nullable=False)
    mcqs_passed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Timing ────────────────────────────────────────────────────────────────
    # Duration in seconds
    time_taken: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ── Timestamps ────────────────────────────────────────────────────────────
    attempted_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    challenge: Mapped["Challenge"] = relationship(
        "Challenge",
        back_populates="attempts",
    )
    user: Mapped["User"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "User",
        back_populates="challenge_attempts",
    )

    @property
    def submitted_code(self) -> str:
        return self.code

    @submitted_code.setter
    def submitted_code(self, value: str) -> None:
        self.code = value

    @property
    def submitted_at(self) -> datetime:
        return self.attempted_at

    @submitted_at.setter
    def submitted_at(self, value: datetime) -> None:
        self.attempted_at = value

    def __repr__(self) -> str:
        return (
            f"<ChallengeAttempt id={self.id} passed={self.passed} "
            f"tests={self.tests_passed}/{self.tests_total}>"
        )
