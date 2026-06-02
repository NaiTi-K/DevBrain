"""
backend/models/progress.py
Daily progress snapshots — one row per user per calendar day.
Used for streak tracking, skill-delta charts, and exam readiness scoring.
"""

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from models.database import Base


class ProgressSnapshot(Base):
    __tablename__ = "progress_snapshots"

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

    # ── Snapshot data ─────────────────────────────────────────────────────────
    # Full skill map at time of snapshot — same format as SkillProfile.skills
    skills_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # ── Challenge metrics ─────────────────────────────────────────────────────
    challenges_done: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    challenges_passed: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    # ── Review metrics ────────────────────────────────────────────────────────
    reviews_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ── Streak ────────────────────────────────────────────────────────────────
    streak_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ── Date of the snapshot ──────────────────────────────────────────────────
    snapshot_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        default=date.today,
        server_default=func.current_date(),
    )

    # ── Constraints ───────────────────────────────────────────────────────────
    __table_args__ = (
        UniqueConstraint("user_id", "snapshot_date", name="uq_progress_user_date"),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    user: Mapped["User"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "User",
        back_populates="progress_snapshots",
    )

    @property
    def skills(self) -> dict:
        """Proxy to skills_snapshot."""
        return self.skills_snapshot

    @skills.setter
    def skills(self, value: dict) -> None:
        self.skills_snapshot = value

    def __repr__(self) -> str:
        return (
            f"<ProgressSnapshot user_id={self.user_id} "
            f"date={self.snapshot_date} streak={self.streak_days}>"
        )
