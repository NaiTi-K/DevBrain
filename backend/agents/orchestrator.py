"""
LangGraph orchestrator for DevBrain AI.

Defines the shared graph state (DevBrainState), intent-routing logic, and the
compiled StateGraph that wires every agent node together.

Part 4 will supply: code_reviewer_node, reflector_node, interview_agent_node,
resource_agent_node. Until then, stub nodes are used so the graph compiles.
"""

from __future__ import annotations

import logging
from typing import Optional

from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════ #
# State definition                                                            #
# ═══════════════════════════════════════════════════════════════════════════ #


class DevBrainState(TypedDict):
    """Shared mutable state passed between all graph nodes."""

    user_id: str
    github_username: str
    intent: str
    current_agent: str
    user_input: str
    agent_output: str
    structured_output: dict
    skill_profile: dict
    conversation_history: list[dict]
    rag_context: list[str]
    reflection_score: float
    iteration_count: int
    max_iterations: int
    error: Optional[str]
    should_continue: bool


# ═══════════════════════════════════════════════════════════════════════════ #
# Intent routing                                                              #
# ═══════════════════════════════════════════════════════════════════════════ #

# Maps intent label → list of trigger keywords (all matched case-insensitively)
_INTENT_KEYWORDS: dict[str, list[str]] = {
    "github_analyze": ["analyze my github", "scan repos", "skill profile"],
    "roadmap": ["roadmap", "learning plan", "what should i learn", "study plan"],
    "challenge": ["challenge", "practice problem", "give me a question", "coding problem"],
    "review": ["review", "check my code", "feedback on", "critique"],
    "interview": ["mock interview", "interview me", "practice interview", "interview question"],
    "resources": ["resource", "tutorial", "how do i learn", "documentation", "where can i learn"],
    "progress": ["progress", "how am i doing", "my stats", "improvement"],
}


def route_intent(state: DevBrainState) -> str:
    """
    Classify the user's message into one of the known intent labels.
    Falls back to "chat" if nothing matches.
    """
    text = (state.get("user_input") or "").lower()

    for intent, keywords in _INTENT_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                return intent

    return "chat"


# ═══════════════════════════════════════════════════════════════════════════ #
# Orchestrator node                                                           #
# ═══════════════════════════════════════════════════════════════════════════ #


def orchestrator_node(state: DevBrainState) -> DevBrainState:
    """
    Entry-point node. Determines intent (if not already set), sets current_agent,
    then the conditional edge routes to the appropriate agent node.
    """
    intent = state.get("intent")
    if not intent:
        intent = route_intent(state)
        logger.info("Orchestrator resolved intent=%s for user=%s", intent, state.get("user_id"))
    else:
        logger.info("Orchestrator using pre-set intent=%s for user=%s", intent, state.get("user_id"))

    return {
        **state,
        "intent": intent,
        "current_agent": intent,
        "error": None,
    }


def _conditional_router(state: DevBrainState) -> str:
    """Used as the conditional edge out of the orchestrator node."""
    intent = state.get("intent", "chat")
    routing_map = {
        "github_analyze": "github_analyzer",
        "roadmap": "roadmap_agent",
        "challenge": "challenge_agent",
        "review": "code_reviewer",
        "interview": "interview_agent",
        "resources": "resource_agent",
        "progress": "progress_agent",
        "chat": "chat_stub",
    }
    return routing_map.get(intent, "chat_stub")


# ═══════════════════════════════════════════════════════════════════════════ #
# Part-4 stub nodes (will be replaced by real implementations)               #
# ═══════════════════════════════════════════════════════════════════════════ #


def _not_implemented_stub(label: str):
    """Factory that returns a stub node function for a given agent label."""

    def _stub(state: DevBrainState) -> DevBrainState:
        logger.warning("Stub node called for agent=%s — not yet implemented.", label)
        return {
            **state,
            "agent_output": f"[{label}] Not yet implemented (Part 4).",
            "error": None,
        }

    _stub.__name__ = f"{label}_stub"
    return _stub


chat_stub_node = _not_implemented_stub("chat")


# ═══════════════════════════════════════════════════════════════════════════ #
# Import real agent nodes                                                     #
# ═══════════════════════════════════════════════════════════════════════════ #

from agents.github_analyzer import github_analyzer_node  # noqa: E402
from agents.roadmap_agent import roadmap_agent_node  # noqa: E402
from agents.challenge_agent import challenge_agent_node  # noqa: E402
from agents.progress_agent import progress_agent_node  # noqa: E402
from agents.code_review_agent import code_review_node as code_reviewer_node  # noqa: E402
from agents.code_review_agent import reflection_node as reflector_node  # noqa: E402
from agents.code_review_agent import should_reflect_again  # noqa: E402

from agents.interview_agent import interview_agent_node  # noqa: E402
from agents.resource_agent import resource_agent_node  # noqa: E402

# ═══════════════════════════════════════════════════════════════════════════ #
# Build the graph                                                             #
# ═══════════════════════════════════════════════════════════════════════════ #

_builder = StateGraph(DevBrainState)

# ── Nodes ──────────────────────────────────────────────────────────────────
_builder.add_node("orchestrator", orchestrator_node)
_builder.add_node("github_analyzer", github_analyzer_node)
_builder.add_node("roadmap_agent", roadmap_agent_node)
_builder.add_node("challenge_agent", challenge_agent_node)
_builder.add_node("progress_agent", progress_agent_node)

# Part-4 stubs
# Part-4 real nodes
_builder.add_node("code_reviewer", code_reviewer_node)
_builder.add_node("reflector", reflector_node)
_builder.add_node("interview_agent", interview_agent_node)
_builder.add_node("resource_agent", resource_agent_node)
_builder.add_node("chat_stub", chat_stub_node)

# ── Entry point ────────────────────────────────────────────────────────────
_builder.set_entry_point("orchestrator")

# ── Edges ──────────────────────────────────────────────────────────────────
_builder.add_conditional_edges(
    "orchestrator",
    _conditional_router,
    {
        "github_analyzer": "github_analyzer",
        "roadmap_agent": "roadmap_agent",
        "challenge_agent": "challenge_agent",
        "progress_agent": "progress_agent",
        "code_reviewer": "code_reviewer",
        "reflector": "reflector",
        "interview_agent": "interview_agent",
        "resource_agent": "resource_agent",
        "chat_stub": "chat_stub",
    },
)

# All agent nodes terminate at END (except code_reviewer and reflector which form a loop)
for _node in [
    "github_analyzer",
    "roadmap_agent",
    "challenge_agent",
    "progress_agent",
    "interview_agent",
    "resource_agent",
    "chat_stub",
]:
    _builder.add_edge(_node, END)

# Code reviewer goes to reflector node
_builder.add_edge("code_reviewer", "reflector")

# Reflector conditional router
_builder.add_conditional_edges(
    "reflector",
    should_reflect_again,
    {"review_again": "code_reviewer", "done": END}
)

# ── Compile ────────────────────────────────────────────────────────────────
app = _builder.compile()

__all__ = ["app", "DevBrainState", "route_intent"]
