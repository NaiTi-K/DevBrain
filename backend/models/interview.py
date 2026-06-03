"""
backend/models/interview.py
Mock technical interview sessions — DSA and system design modes.
"""

import uuid
from datetime import datetime

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from models.database import Base


class InterviewSession(Base):
    __tablename__ = "interview_sessions"

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

    # ── Interview mode ────────────────────────────────────────────────────────
    # "dsa" | "system_design"
    mode: Mapped[str] = mapped_column(String(20), nullable=False)

    # ── Conversation history ──────────────────────────────────────────────────
    # Ordered list of turn dicts:
    # [
    #   {"role": "assistant", "content": "Let's start. Given an array..."},
    #   {"role": "user",      "content": "I would use a hash map..."},
    #   ...
    # ]
    messages: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # ── Scoring (set when session ends) ──────────────────────────────────────
    score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # ── Topics actually covered during the session ────────────────────────────
    # Example: ["Binary Search", "Recursion", "Time Complexity"]
    topics_covered: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        server_default=func.now(),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    user: Mapped["User"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "User",
        back_populates="interview_sessions",
    )

    def __init__(self, **kwargs):
        # Map conversation_history -> messages
        if "conversation_history" in kwargs:
            kwargs["messages"] = kwargs.pop("conversation_history")

        # Map overall_score -> score
        if "overall_score" in kwargs:
            kwargs["score"] = kwargs.pop("overall_score")

        # Map structured_output -> topics_covered (JSONB)
        structured_output = kwargs.pop("structured_output", {}) or {}

        # If completed is passed, store inside structured_output
        if "completed" in kwargs:
            structured_output["completed"] = kwargs.pop("completed")

        # If updated_at is passed, drop/ignore it (or store inside structured_output)
        if "updated_at" in kwargs:
            kwargs.pop("updated_at")

        kwargs["topics_covered"] = structured_output
        super().__init__(**kwargs)

    @property
    def conversation_history(self) -> list:
        return self.messages

    @conversation_history.setter
    def conversation_history(self, value: list) -> None:
        self.messages = value

    @property
    def overall_score(self) -> float | None:
        return self.score

    @overall_score.setter
    def overall_score(self, value: float | None) -> None:
        self.score = value

    @property
    def structured_output(self) -> dict:
        return self.topics_covered if isinstance(self.topics_covered, dict) else {}

    @structured_output.setter
    def structured_output(self, value: dict) -> None:
        self.topics_covered = value

    @property
    def completed(self) -> bool:
        return self.structured_output.get("completed", False)

    @completed.setter
    def completed(self, value: bool) -> None:
        so = dict(self.structured_output)
        so["completed"] = value
        self.structured_output = so

    def __repr__(self) -> str:
        return f"<InterviewSession id={self.id} mode={self.mode} turns={len(self.messages) if self.messages else 0}>"
