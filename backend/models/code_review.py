"""
backend/models/code_review.py
Stores AI code reviews, including the multi-loop reflection data.
"""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from models.database import Base


class CodeReview(Base):
    __tablename__ = "code_reviews"

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

    # ── Input ─────────────────────────────────────────────────────────────────
    language: Mapped[str] = mapped_column(String(50), nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)

    # ── Review output ─────────────────────────────────────────────────────────
    # Structure (produced by LangGraph code_review_agent):
    # {
    #   "score": 7,                          # 0-10
    #   "annotations": [
    #     {"line": 12, "severity": "warning", "message": "Unused variable `x`"}
    #   ],
    #   "complexity": "O(n log n)",
    #   "improvements": [
    #     "Use a dictionary for O(1) lookups instead of a nested loop"
    #   ]
    # }
    review: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # ── Self-reflection loops ─────────────────────────────────────────────────
    # How many times the LangGraph cycle iterated before quality >= 0.75
    reflection_loops: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

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
        back_populates="code_reviews",
    )

    def __init__(self, **kwargs):
        # Extract fields that belong to the `review` dict
        review_fields = ["score", "annotations", "complexity", "edge_cases", "improvements", "best_practices", "summary"]
        review_dict = kwargs.pop("review", {}) or {}
        for field in review_fields:
            if field in kwargs:
                review_dict[field] = kwargs.pop(field)

        # Keep track of custom/missing fields by storing them in the JSONB review dict
        if "context" in kwargs:
            review_dict["context"] = kwargs.pop("context")
        if "reflection_score" in kwargs:
            review_dict["reflection_score"] = kwargs.pop("reflection_score")

        kwargs["review"] = review_dict
        super().__init__(**kwargs)

    @property
    def score(self) -> int:
        return self.review.get("score", 0) if isinstance(self.review, dict) else 0

    @property
    def summary(self) -> str:
        return self.review.get("summary", "") if isinstance(self.review, dict) else ""

    def __repr__(self) -> str:
        score = self.review.get("score") if isinstance(self.review, dict) else "?"
        return (
            f"<CodeReview id={self.id} lang={self.language} "
            f"score={score} loops={self.reflection_loops}>"
        )
