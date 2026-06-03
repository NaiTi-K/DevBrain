"""
backend/models/skill_profile.py
Stores the skill vector derived from a user's GitHub repositories.
"""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from models.database import Base


class SkillProfile(Base):
    __tablename__ = "skill_profiles"

    # ── Primary key ──────────────────────────────────────────────────────────
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )

    # ── Foreign key ───────────────────────────────────────────────────────────
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Skill data ────────────────────────────────────────────────────────────
    # Example: {"Python": 0.82, "JavaScript": 0.45, "Docker": 0.30}
    skills: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # ── Repository stats ──────────────────────────────────────────────────────
    repo_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Timestamps ────────────────────────────────────────────────────────────
    analyzed_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        server_default=func.now(),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    user: Mapped["User"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "User",
        back_populates="skill_profiles",
    )

    # ── Additional indexes ────────────────────────────────────────────────────
    __table_args__ = (Index("ix_skill_profiles_user_analyzed", "user_id", "analyzed_at"),)

    def __init__(self, **kwargs):
        if "github_username" in kwargs:
            kwargs.pop("github_username")
        super().__init__(**kwargs)

    @property
    def github_username(self) -> str:
        return self.user.github_username if self.user else ""

    @github_username.setter
    def github_username(self, value: str) -> None:
        pass

    def __repr__(self) -> str:
        return f"<SkillProfile user_id={self.user_id} analyzed_at={self.analyzed_at}>"
