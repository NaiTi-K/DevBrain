"""
Abstract base class for all DevBrain agents.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.orchestrator import DevBrainState


class BaseAgent(ABC):
    """
    Abstract base for every agent node in the DevBrain graph.
    Subclasses implement `run()` and may call helper utilities defined here.
    """

    def __init__(self, name: str) -> None:
        self.name = name

    @abstractmethod
    async def run(self, state: "DevBrainState") -> "DevBrainState":
        """
        Execute the agent's logic against the current graph state.
        Must return a (possibly mutated) copy of `state`.
        """
        raise NotImplementedError(f"{self.name}.run() is not implemented.")

    # ------------------------------------------------------------------ #
    # Shared helpers                                                       #
    # ------------------------------------------------------------------ #

    def _format_skill_profile(self, skills: dict) -> str:
        """
        Convert a raw skills dict  {"Python": 0.82, "JavaScript": 0.45, ...}
        into a human-readable string.

        Level thresholds
        ----------------
        score < 0.30  →  Beginner
        0.30 ≤ score ≤ 0.65  →  Intermediate
        score > 0.65  →  Advanced
        """
        if not skills:
            return "No skills detected yet."

        parts: list[str] = []
        for skill, score in sorted(skills.items(), key=lambda x: x[1], reverse=True):
            if score < 0.30:
                level = "Beginner"
            elif score <= 0.65:
                level = "Intermediate"
            else:
                level = "Advanced"
            parts.append(f"{skill}: {level} ({score:.2f})")

        return ", ".join(parts)

    def _skill_level(self, score: float) -> str:
        """Return the textual level for a single score."""
        if score < 0.30:
            return "Beginner"
        elif score <= 0.65:
            return "Intermediate"
        return "Advanced"

    def _difficulty_from_score(self, score: float) -> str:
        """Map a skill score to a challenge difficulty label."""
        if score < 0.30:
            return "easy"
        elif score <= 0.65:
            return "medium"
        return "hard"
