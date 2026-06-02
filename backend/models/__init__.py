"""
backend/models/__init__.py

Import every ORM model here so that:
  1. Base.metadata is fully populated when Alembic runs autogenerate.
  2. Downstream code can do `from models import User` instead of
     `from models.user import User`.
"""

from models.challenge import Challenge, ChallengeAttempt
from models.code_review import CodeReview
from models.database import Base, async_session, engine
from models.interview import InterviewSession
from models.progress import ProgressSnapshot
from models.roadmap import Roadmap
from models.skill_profile import SkillProfile
from models.user import User

__all__ = [
    # Engine / session helpers
    "Base",
    "engine",
    "async_session",
    # ORM models
    "User",
    "SkillProfile",
    "Roadmap",
    "Challenge",
    "ChallengeAttempt",
    "CodeReview",
    "InterviewSession",
    "ProgressSnapshot",
]
