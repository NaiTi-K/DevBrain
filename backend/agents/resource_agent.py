"""
Resource Finder Agent (RAG: ChromaDB + Tavily)
===============================================
ORCHESTRATOR INTEGRATION (backend/agents/orchestrator.py):
  Add this import:

    from agents.resource_agent import resource_agent_node

  Register the node:

    graph.add_node("resource_finder", resource_agent_node)

  Wire edges as appropriate for your routing logic (e.g., from router → resource_finder → END).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlparse

from agents.orchestrator import DevBrainState
from services.llm_service import llm
from services.vector_store import vector_store
from services.search_service import search_service

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Source quality weights  (higher = more trustworthy)
# ─────────────────────────────────────────────────────────────────────────────

_OFFICIAL_DOCS_DOMAINS = {
    "docs.python.org", "docs.djangoproject.com", "fastapi.tiangolo.com",
    "react.dev", "nextjs.org", "docs.docker.com", "kubernetes.io",
    "developer.mozilla.org", "docs.github.com", "postgresql.org",
    "redis.io", "docs.aws.amazon.com", "cloud.google.com",
    "learn.microsoft.com", "docs.sqlalchemy.org", "langchain.com",
    "python.langchain.com",
}
_GITHUB_DOMAIN = "github.com"
_TUTORIAL_DOMAINS = {
    "realpython.com", "testdriven.io", "css-tricks.com",
    "digitalocean.com", "scotch.io", "tutorialspoint.com",
    "w3schools.com", "geeksforgeeks.org",
}


def _source_quality(url: str) -> float:
    """Return a quality weight based on the URL's domain."""
    try:
        domain = urlparse(url).netloc.lstrip("www.")
    except Exception:
        return 0.5

    if domain in _OFFICIAL_DOCS_DOMAINS:
        return 1.0
    if domain == _GITHUB_DOMAIN or domain.endswith(".github.io"):
        return 0.9
    if domain in _TUTORIAL_DOMAINS:
        return 0.7
    return 0.5


def _rank_resources(resources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Sort resources by composite score:
        score = confidence * 0.6 + source_quality * 0.4
    Deduplicates by URL first.
    """
    seen_urls: set[str] = set()
    unique: list[dict] = []
    for r in resources:
        url = r.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique.append(r)

    def composite(r: dict) -> float:
        confidence = float(r.get("confidence", 0.5))
        sq = _source_quality(r.get("url", ""))
        r["source_quality"] = sq  # store for downstream use
        return confidence * 0.6 + sq * 0.4

    unique.sort(key=composite, reverse=True)
    return unique


def _get_skill_level(state: DevBrainState, topic: str) -> str:
    """
    Returns 'beginner', 'intermediate', or 'advanced' for the given topic.
    Falls back to 'intermediate' if the skill profile is missing.
    """
    skill_profile: dict = {}
    user = state.get("user")
    if user and hasattr(user, "skill_profile"):
        skill_profile = getattr(user.skill_profile, "skills", {}) or {}
    elif isinstance(state.get("structured_output"), dict):
        skill_profile = state["structured_output"].get("skill_profile", {})

    # Normalise topic key for lookup
    topic_lower = topic.lower().replace(" ", "_")
    score: float = 0.5  # default to intermediate if unknown

    for key, val in skill_profile.items():
        if key.lower().replace(" ", "_") == topic_lower:
            if isinstance(val, dict):
                score = float(val.get("score", 0.5))
            elif isinstance(val, (int, float)):
                score = float(val)
            break

    if score < 0.35:
        return "beginner"
    if score < 0.70:
        return "intermediate"
    return "advanced"


# ─────────────────────────────────────────────────────────────────────────────
# Agent node
# ─────────────────────────────────────────────────────────────────────────────

async def resource_agent_node(state: DevBrainState) -> DevBrainState:
    """
    RAG-powered resource finder.

    Steps
    -----
    1. Extract topic from user query via Grok (fast, max_tokens=100).
    2. Determine skill level from the user's skill profile.
    3. Semantic search in ChromaDB (high-confidence threshold < 0.3 distance).
    4. Supplement with Tavily if fewer than 3 high-confidence results.
    5. Add Tavily results back into ChromaDB for future cache hits.
    6. Deduplicate, rank by composite score.
    7. Generate a learning-path narrative via Grok.
    """
    query: str = state.get("user_input", "")
    if isinstance(query, dict):
        query = query.get("query", "")

    # ── Step 1: extract topic ──────────────────────────────────────────────
    topic = query  # safe fallback
    try:
        topic_raw = await llm.call(
            prompt=f"Extract the programming topic from: '{query}'. Return only the topic name, nothing else.",
            system="You extract programming topics. Respond with 2-4 words maximum.",
            max_tokens=100,
        )
        topic = topic_raw.strip().strip('"').strip("'")
    except Exception as exc:
        logger.warning("Topic extraction failed, using raw query: %s", exc)

    # ── Step 2: skill level ────────────────────────────────────────────────
    skill_level = _get_skill_level(state, topic)
    logger.info("resource_agent: topic=%r skill=%s", topic, skill_level)

    # ── Step 3: ChromaDB search ────────────────────────────────────────────
    chroma_results: list[dict] = []
    try:
        raw = await vector_store.search_resources(query=topic, n_results=5)
        for r in raw:
            r.setdefault("confidence", max(0.0, 1.0 - float(r.get("distance", 0.5))))
        chroma_results = raw
    except Exception as exc:
        logger.warning("ChromaDB search failed: %s", exc)

    high_confidence = [r for r in chroma_results if float(r.get("distance", 1.0)) < 0.3]

    # ── Step 4: supplement with Tavily ────────────────────────────────────
    web_results: list[dict] = []
    if len(high_confidence) < 3:
        needed = 3 - len(high_confidence)
        try:
            raw_web = await search_service.search_resources(topic, difficulty=skill_level)
            web_results = raw_web[:needed + 2]  # fetch a few extra before dedup

            # Back-fill ChromaDB so next search for the same topic is faster
            add_tasks = [
                vector_store.add_resource(
                    title=r.get("title", "Untitled"),
                    url=r.get("url", ""),
                    description=r.get("description", r.get("snippet", "")),
                    topic=topic,
                    difficulty=skill_level,
                    source=r.get("source", urlparse(r.get("url", "")).netloc),
                )
                for r in web_results
                if r.get("url")
            ]
            if add_tasks:
                await asyncio.gather(*add_tasks, return_exceptions=True)
        except Exception as exc:
            logger.warning("Tavily search failed: %s", exc)

    # ── Step 5: merge, deduplicate, rank ──────────────────────────────────
    def _normalise(r: dict, source_label: str) -> dict:
        return {
            "title": r.get("title", "Untitled"),
            "url": r.get("url", ""),
            "difficulty": r.get("difficulty", skill_level),
            "source": r.get("source", source_label),
            "description": r.get("description", r.get("snippet", "")),
            "confidence": float(r.get("confidence", 0.5)),
            "why_recommended": "",  # filled in after ranking
        }

    all_resources = (
        [_normalise(r, "chromadb") for r in chroma_results]
        + [_normalise(r, "web") for r in web_results]
    )
    ranked = _rank_resources(all_resources)[:8]  # top 8

    # Fill why_recommended based on source
    for r in ranked:
        sq = r.get("source_quality", 0.5)
        if sq == 1.0:
            r["why_recommended"] = "Official documentation — authoritative and up-to-date."
        elif sq == 0.9:
            r["why_recommended"] = "High-quality open-source resource on GitHub."
        elif sq == 0.7:
            r["why_recommended"] = "Reputable tutorial site with practical examples."
        else:
            r["why_recommended"] = "Community resource with relevant coverage of the topic."

    # ── Step 6: learning path narrative ───────────────────────────────────
    resource_titles = "\n".join(
        f"{i+1}. {r['title']} ({r['url']})"
        for i, r in enumerate(ranked[:6])
    )
    learning_path = ""
    try:
        learning_path = await llm.call(
            prompt=(
                f"Given these resources for {topic}, write a 2-sentence guide "
                f"on how to use them in order:\n{resource_titles}"
            ),
            system=(
                "You write concise, actionable learning paths for developers. "
                f"Assume the learner is at {skill_level} level."
            ),
            max_tokens=200,
        )
    except Exception as exc:
        logger.warning("Learning path generation failed: %s", exc)
        learning_path = (
            f"Start with the first resource to build foundational knowledge of {topic}, "
            "then progress through the remaining resources for deeper understanding."
        )

    # ── Step 7: persist to state ───────────────────────────────────────────
    output_resources = [
        {
            "title": r["title"],
            "url": r["url"],
            "difficulty": r["difficulty"],
            "source": r["source"],
            "why_recommended": r["why_recommended"],
        }
        for r in ranked
    ]

    state["structured_output"] = {
        "resources": output_resources,
        "learning_path": learning_path,
        "topic": topic,
        "skill_level": skill_level,
    }

    formatted_list = "\n".join(
        f"{i+1}. [{r['title']}]({r['url']}) — {r['difficulty']} — {r['why_recommended']}"
        for i, r in enumerate(output_resources)
    )
    state["agent_output"] = f"{learning_path}\n\n**Resources:**\n{formatted_list}"

    logger.info("resource_agent_node complete — %d resources for topic=%r", len(output_resources), topic)
    return state


# ─────────────────────────────────────────────────────────────────────────────
# Seed function
# ─────────────────────────────────────────────────────────────────────────────

# 20 curated resources covering the required topics
_SEED_RESOURCES: list[dict[str, str]] = [
    # Trees / Graphs
    {
        "title": "Visualgo — Tree & Graph Visualisations",
        "description": "Interactive visualisation of BST, AVL, segment trees, and graph algorithms.",
        "url": "https://visualgo.net/en/bst",
        "topic": "trees_graphs",
        "difficulty": "beginner",
    },
    {
        "title": "CP-Algorithms — Graph Theory",
        "description": "In-depth explanations of DFS, BFS, shortest paths, spanning trees, and more.",
        "url": "https://cp-algorithms.com/graph/breadth-first-search.html",
        "topic": "trees_graphs",
        "difficulty": "intermediate",
    },
    # Dynamic Programming
    {
        "title": "LeetCode — Dynamic Programming Study Plan",
        "description": "Curated DP problems from easy to hard with editorial solutions.",
        "url": "https://leetcode.com/studyplan/dynamic-programming/",
        "topic": "dynamic_programming",
        "difficulty": "beginner",
    },
    {
        "title": "Algorithms Illuminated — DP Chapter (Stanford Online)",
        "description": "University-level DP coverage including memoisation and bottom-up tabulation.",
        "url": "https://www.algorithmsilluminated.org/",
        "topic": "dynamic_programming",
        "difficulty": "advanced",
    },
    # System Design
    {
        "title": "System Design Primer (GitHub)",
        "description": "Comprehensive repo covering scalability, load balancing, caching, databases, etc.",
        "url": "https://github.com/donnemartin/system-design-primer",
        "topic": "system_design",
        "difficulty": "intermediate",
    },
    {
        "title": "ByteByteGo — System Design Newsletter",
        "description": "Visual explanations of real-world distributed systems by Alex Xu.",
        "url": "https://bytebytego.com/",
        "topic": "system_design",
        "difficulty": "intermediate",
    },
    # Python async
    {
        "title": "Python asyncio Official Docs",
        "description": "Official documentation for Python's asyncio library with examples.",
        "url": "https://docs.python.org/3/library/asyncio.html",
        "topic": "python_async",
        "difficulty": "beginner",
    },
    {
        "title": "Real Python — Async IO in Python: A Complete Walkthrough",
        "description": "Deep dive into coroutines, event loops, and concurrent I/O patterns.",
        "url": "https://realpython.com/async-io-python/",
        "topic": "python_async",
        "difficulty": "intermediate",
    },
    # SQL optimisation
    {
        "title": "Use The Index, Luke!",
        "description": "Developer-focused guide to SQL indexing and query optimisation across databases.",
        "url": "https://use-the-index-luke.com/",
        "topic": "sql_optimization",
        "difficulty": "intermediate",
    },
    {
        "title": "PostgreSQL Query Optimisation (Official Docs)",
        "description": "EXPLAIN, ANALYZE, and planner statistics in PostgreSQL.",
        "url": "https://www.postgresql.org/docs/current/performance-tips.html",
        "topic": "sql_optimization",
        "difficulty": "advanced",
    },
    # Docker basics
    {
        "title": "Docker Official Get Started Guide",
        "description": "Step-by-step introduction to containers, images, and Docker Compose.",
        "url": "https://docs.docker.com/get-started/",
        "topic": "docker_basics",
        "difficulty": "beginner",
    },
    {
        "title": "Docker Deep Dive (GitHub Repo)",
        "description": "Practical Dockerfile patterns, multi-stage builds, and networking.",
        "url": "https://github.com/nigelpoulton/ddd-book",
        "topic": "docker_basics",
        "difficulty": "intermediate",
    },
    # React fundamentals
    {
        "title": "React Official Documentation",
        "description": "Official React docs covering components, hooks, and the new App Router.",
        "url": "https://react.dev/learn",
        "topic": "react_fundamentals",
        "difficulty": "beginner",
    },
    {
        "title": "Kent C. Dodds — Epic React",
        "description": "Advanced patterns, performance, and testing in React.",
        "url": "https://epicreact.dev/",
        "topic": "react_fundamentals",
        "difficulty": "advanced",
    },
    # REST API design
    {
        "title": "Microsoft REST API Guidelines (GitHub)",
        "description": "Production-grade guidelines for naming, versioning, errors, and pagination.",
        "url": "https://github.com/microsoft/api-guidelines/blob/vNext/azure/Guidelines.md",
        "topic": "rest_api_design",
        "difficulty": "intermediate",
    },
    {
        "title": "FastAPI Official Documentation",
        "description": "Complete guide to building high-performance REST APIs with FastAPI.",
        "url": "https://fastapi.tiangolo.com/",
        "topic": "rest_api_design",
        "difficulty": "beginner",
    },
    # Git workflows
    {
        "title": "Atlassian Git Tutorials",
        "description": "Branching strategies, rebase vs merge, and team workflows explained visually.",
        "url": "https://www.atlassian.com/git/tutorials",
        "topic": "git_workflows",
        "difficulty": "beginner",
    },
    {
        "title": "Pro Git Book (Free Online)",
        "description": "Definitive open-source book on Git internals, branching, and distributed workflows.",
        "url": "https://git-scm.com/book/en/v2",
        "topic": "git_workflows",
        "difficulty": "intermediate",
    },
    # Big-O complexity
    {
        "title": "Big-O Cheat Sheet",
        "description": "Quick reference for time and space complexities of common algorithms and data structures.",
        "url": "https://www.bigocheatsheet.com/",
        "topic": "big_o_complexity",
        "difficulty": "beginner",
    },
    {
        "title": "MIT OpenCourseWare — Introduction to Algorithms (6.006)",
        "description": "Full lecture notes, problem sets, and exams for MIT's algorithms course.",
        "url": "https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-spring-2020/",
        "topic": "big_o_complexity",
        "difficulty": "advanced",
    },
]


async def seed_resource_collection() -> tuple[int, list[str]]:
    """
    Seed ChromaDB with 20 curated resources at application startup.
    Idempotent — uses the URL as a stable document ID so duplicates are upserted.

    Returns (seeded_count, error_messages).
    """
    seeded = 0
    errors: list[str] = []
    total = len(_SEED_RESOURCES)

    for resource in _SEED_RESOURCES:
        try:
            vector_store.add_resource(
                resource_id=resource["url"],
                title=resource["title"],
                description=resource["description"],
                topic=resource["topic"],
                difficulty=resource["difficulty"],
                url=resource["url"],
                source=urlparse(resource["url"]).netloc.lstrip("www."),
            )
            seeded += 1
        except Exception as exc:
            msg = f"{resource['title']}: {exc}"
            errors.append(msg)
            logger.warning("Failed to seed resource: %s", msg)

    logger.info(
        "seed_resource_collection complete — %d/%d resources seeded.",
        seeded,
        total,
    )
    if seeded == 0 and errors:
        logger.error("All seed operations failed. First error: %s", errors[0])

    return seeded, errors
