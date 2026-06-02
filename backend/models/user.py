"""
backend/models/user.py
SQLAlchemy ORM model for authenticated GitHub users.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from models.database import Base
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models.skill_profile import SkillProfile

class User(Base):
    __tablename__ = "users"

    # ── Primary key ──────────────────────────────────────────────────────────
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )

    # ── GitHub identity ───────────────────────────────────────────────────────
    github_id: Mapped[int] = mapped_column(
        Integer,
        unique=True,
        nullable=False,
        index=True,
    )
    github_username: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
    )

    # ── Profile fields ────────────────────────────────────────────────────────
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    resume_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Career target ─────────────────────────────────────────────────────────
    # Allowed values: "SDE Intern", "Backend", "ML", "Full-Stack", "DevOps"
    target_role: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    skill_profiles: Mapped[list["SkillProfile"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "SkillProfile",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="select",
    )
    roadmaps: Mapped[list["Roadmap"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Roadmap",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="select",
    )
    challenges: Mapped[list["Challenge"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Challenge",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="select",
    )
    challenge_attempts: Mapped[list["ChallengeAttempt"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "ChallengeAttempt",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="select",
    )
    code_reviews: Mapped[list["CodeReview"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "CodeReview",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="select",
    )
    interview_sessions: Mapped[list["InterviewSession"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "InterviewSession",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="select",
    )
    progress_snapshots: Mapped[list["ProgressSnapshot"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "ProgressSnapshot",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="select",
    )

    # ── Additional index ──────────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_users_github_username", "github_username"),
    )

    @property
    def skill_profile(self) -> "SkillProfile" | None:
        """Helper property to retrieve the most recent skill profile."""
        if not self.skill_profiles:
            return None
        return sorted(self.skill_profiles, key=lambda p: p.analyzed_at or datetime.min, reverse=True)[0]

    def __repr__(self) -> str:
        return f"<User id={self.id} github={self.github_username}>"
