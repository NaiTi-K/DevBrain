"""
Challenge Agent
===============
Generates an adaptive coding challenge targeting the user's weakest skill area,
persists it to PostgreSQL, and provides a sandboxed evaluation function for
submitted solutions.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime
from typing import Optional

from models.database import async_session
from models.challenge import Challenge
from services.cache_service import cache
from services.llm_service import llm

logger = logging.getLogger(__name__)

# ── Validation ─────────────────────────────────────────────────────────────
VALID_TYPES = {
    "int", "long", "float", "double", "bool", "string", "char",
    "int[]", "long[]", "float[]", "double[]", "bool[]", "string[]", "char[]",
    "int[][]", "string[][]", "List<int>", "List<string>", "List<List<int>>"
}

VALID_JUDGES = {"exact", "any_order"}

def validate_schema(schema: dict) -> None:
    """Raises ValueError with a descriptive message if schema is invalid."""
    if not schema:
        raise ValueError("Missing 'schema' object in challenge.")

    params = schema.get("params", [])
    if not isinstance(params, list) or len(params) == 0:
        raise ValueError("schema.params must be a non-empty list.")

    for p in params:
        if p.get("type") not in VALID_TYPES:
            raise ValueError(
                f"Unsupported type '{p.get('type')}' in schema.params. "
                f"Must be one of: {VALID_TYPES}"
            )

    ret = schema.get("returns")
    if ret not in VALID_TYPES:
        raise ValueError(f"Unsupported return type '{ret}'.")

    judge = schema.get("judge", "exact")
    if judge not in VALID_JUDGES and not judge.startswith("epsilon:"):
        raise ValueError(
            f"Invalid judge '{judge}'. Must be 'exact', 'any_order', or 'epsilon:<tol>'."
        )

# ── Skill → coding topic mapping ──────────────────────────────────────────
_SKILL_TO_TOPIC: dict[str, str] = {
    "Python": "data structures and algorithms",
    "JavaScript": "hash maps and arrays",
    "TypeScript": "two pointers and sliding window",
    "Java": "object-oriented design (e.g. LRU Cache)",
    "C++": "pointers and linked lists",
    "C": "bit manipulation and math",
    "Go": "trees and graphs",
    "Rust": "dynamic programming",
    "SQL": "binary search",
    "HTML": "stacks and queues",
    "CSS": "greedy algorithms",
    "Ruby": "sorting and searching",
    "PHP": "string manipulation",
    "Swift": "intervals and matrices",
    "Kotlin": "backtracking",
    "R": "tries and advanced structures",
    "Scala": "heaps and priority queues",
    "Haskell": "divide and conquer",
    "MATLAB": "math and geometry",
}

_DEFAULT_TOPIC = "algorithms and problem solving"


# ═══════════════════════════════════════════════════════════════════════════ #
# Agent node                                                                  #
# ═══════════════════════════════════════════════════════════════════════════ #


async def challenge_agent_node(state: dict) -> dict:
    """
    LangGraph node: generate an adaptive coding challenge.
    """
    user_id: str = state["user_id"]

    try:
        # 1. Resolve skill profile
        skill_profile: dict = state.get("skill_profile") or {}
        skills: dict[str, float] = skill_profile.get("skills", {})

        if not skills:
            cached = await cache.get_skill_profile(user_id)
            if cached:
                skills = cached.get("skills", {})

        last_topic = _TOPIC_MEMORY.get(user_id, "")
        weak_skill, weak_score = _find_weakest_coding_skill(skills, last_topic)
        topic: str = _SKILL_TO_TOPIC.get(weak_skill, _DEFAULT_TOPIC)
        difficulty: str = _difficulty_from_score(weak_score)
        primary_lang: str = weak_skill if weak_skill in ["Python", "JavaScript", "C++"] else "Python"

        from services.search_service import search_service
        search_query = f"leetcode exact problem description constraints test cases {topic} {difficulty}"
        search_results = await search_service.search(search_query, max_results=3, search_depth="advanced")
        
        search_context = ""
        if search_results:
            search_context = "\n\n".join(
                f"Source: {res['url']}\nContent: {res['content']}"
                for res in search_results
            )

        prompt = _build_challenge_prompt(topic=topic, difficulty=difficulty, language=primary_lang, skill=weak_skill, search_context=search_context)

        challenge_dict = None
        for attempt in range(4):
            temp = 0.8 + (attempt * 0.05)
            raw: str = await llm.structured_call(prompt, temperature=temp)
            parsed: Optional[dict] = _parse_json_safe(raw)
            if not parsed or "title" not in parsed:
                continue
            
            try:
                validate_schema(parsed.get("schema", {}))
            except ValueError as e:
                # Retry once with correction
                correction_prompt = f"Your previous schema was invalid: {e}. Fix it and return the full JSON again."
                try:
                    raw2 = await llm.structured_call(correction_prompt, temperature=0.6)
                    parsed = _parse_json_safe(raw2)
                    if parsed: validate_schema(parsed.get("schema", {}))
                except Exception:
                    continue
            
            # Verify solution against test cases
            solution_code = parsed.get("solution", "").replace("\\n", "\n")
            starter_code = parsed.get("starter_code", "").replace("\\n", "\n")
            test_cases = parsed.get("test_cases", [])
            
            if not solution_code or not test_cases:
                continue
                
            from services.sandbox_service import run_code
            import asyncio
            
            schema = parsed.get("schema", {})
            eval_result = await asyncio.to_thread(
                run_code, "python", solution_code, schema, test_cases, schema.get("judge", "exact")
            )
            
            if eval_result.get("status") != "AC":
                err_msg = eval_result.get("stderr") or "Some test cases failed."
                correction_prompt = f"Your generated solution failed against your own test cases! Fix the test cases or the solution. Error: {err_msg}"
                try:
                    raw3 = await llm.structured_call(correction_prompt, temperature=0.6)
                    parsed3 = _parse_json_safe(raw3)
                    if parsed3 and "solution" in parsed3:
                        parsed = parsed3
                except Exception:
                    pass
                continue
                
            challenge_dict = parsed
            break

        if not challenge_dict and parsed:
            logger.error("Failed to generate a passing challenge after 4 attempts. Falling back to the last generated challenge.")
            challenge_dict = parsed
        elif not challenge_dict:
            raise ValueError("Failed to generate a challenge after 4 attempts.")

        challenge_dict.setdefault("difficulty", difficulty)
        challenge_dict.setdefault("topic", topic)
        challenge_dict.setdefault("language", primary_lang)

        async with async_session() as session:
            challenge = Challenge(
                id=uuid.uuid4(),
                user_id=uuid.UUID(user_id),
                title=challenge_dict.get("title", "Untitled Challenge"),
                description=challenge_dict.get("description", ""),
                difficulty=challenge_dict.get("difficulty", difficulty),
                topic=challenge_dict.get("topic", topic),
                constraints=challenge_dict.get("constraints", []),
                examples=challenge_dict.get("examples", []),
                mcqs=challenge_dict.get("mcqs", []),
                test_cases=challenge_dict.get("test_cases", []),
                starter_codes=challenge_dict.get("starter_codes", {}),
                solution=challenge_dict.get("solution", "").replace("\\n", "\n"),
                schema=challenge_dict.get("schema", {}),
                judge=challenge_dict.get("schema", {}).get("judge", "exact"),
                created_at=datetime.utcnow(),
            )
            session.add(challenge)
            await session.commit()
            await session.refresh(challenge)

        challenge_dict["id"] = str(challenge.id)
        agent_output = _format_challenge_display(challenge_dict)
        _TOPIC_MEMORY[user_id] = topic

        return {
            **state,
            "structured_output": challenge_dict,
            "agent_output": agent_output,
            "error": None,
        }

    except Exception as exc:  # noqa: BLE001
        logger.exception("challenge_agent_node failed: %s", exc)
        return {
            **state,
            "agent_output": "Failed to generate a challenge. Please try again.",
            "error": str(exc),
        }


# ═══════════════════════════════════════════════════════════════════════════ #



# ═══════════════════════════════════════════════════════════════════════════ #
# Private helpers                                                             #
# ═══════════════════════════════════════════════════════════════════════════ #


_TOPIC_MEMORY: dict[str, str] = {}  # user_id -> last_topic

def _find_weakest_coding_skill(skills: dict[str, float], last_topic: str = "") -> tuple[str, float]:
    """Return (skill_name, score) for the weakest skill, avoiding last_topic if possible."""
    coding_skills = {k: v for k, v in skills.items() if k in _SKILL_TO_TOPIC and _SKILL_TO_TOPIC[k] != last_topic}
    if not coding_skills:
        # Fallback if all skills are the last topic (unlikely but possible)
        coding_skills = {k: v for k, v in skills.items() if k in _SKILL_TO_TOPIC}
    if not coding_skills:
        return "Python", 0.0
    skill = min(coding_skills, key=coding_skills.get)  # type: ignore[arg-type]
    return skill, coding_skills[skill]

def _difficulty_from_score(score: float) -> str:
    if score <= 0.40:
        return "medium"
    return "hard"



def _build_challenge_prompt(topic: str, difficulty: str, language: str, skill: str, search_context: str) -> str:
    context_block = f"\n=== INTERNET SEARCH CONTEXT ===\n{search_context}\n================================\n" if search_context else ""

    return f"""You are a senior competitive programming coach creating coding challenges.
{context_block}
Target skill: {skill}
Topic area  : {topic}
Difficulty  : {difficulty}

Generate ONE coding challenge as a single JSON object.
CRITICAL INSTRUCTION: Do NOT invent a new problem. You MUST base this on a real, published competitive programming problem (e.g. from LeetCode or GeeksforGeeks) matching the topic.
Use the Internet Search Context above to extract a real problem statement, its mathematical constraints, and its proven test cases.
Make sure to pick a UNIQUE and INTERESTING problem. Do NOT repeatedly generate basic problems like "Two Sum" or "Find Duplicate in Array" unless specifically requested. Provide a different classic problem each time!

{{
  "title": "Exact Title of the Real Problem",
  "description": "Full problem statement exactly as published.",
  "difficulty": "{difficulty}",
  "topic": "{topic}",
  "constraints": ["constraint 1"],
  "examples": [
    {{"input": "example input", "output": "example output", "explanation": "why"}}
  ],
  "test_cases": [
    {{"input": {{"arr": [1, 2], "target": 3}}, "expected": "[1, 2]", "type": "empty_input"}},
    {{"input": {{"arr": [], "target": 0}}, "expected": "[]", "type": "single_element"}}
  ],
  "schema": {{
    "params": [
      {{"name": "arr", "type": "int[]"}},
      {{"name": "target", "type": "int"}}
    ],
    "returns": "int[]",
    "judge": "exact"
  }},
  "mcqs": [
    {{"question": "System Design: Which DB is best for a highly connected social graph?", "options": ["PostgreSQL", "Neo4j", "Redis", "MongoDB"], "correct_index": 1, "explanation": "Neo4j is a graph database..."}},
    {{"question": "DBMS: What is a covering index?", "options": ["Option A", "Option B", "Option C", "Option D"], "correct_index": 0, "explanation": "..."}},
    {{"question": "OOP: What is the primary purpose of the Factory pattern?", "options": ["Option A", "Option B", "Option C", "Option D"], "correct_index": 0, "explanation": "..."}}
  ],
  "starter_codes": {{
    "python": "def solution(...):\n    pass",
    "cpp": "#include <iostream>\n#include <vector>\nusing namespace std;\n\nvector<int> solution(...) {{\n    return {{}};\n}}",
    "java": "import java.util.*;\n\nclass Solution {{\n    public static int[] solution(...) {{\n        return new int[]{{}};\n    }}\n}}"
  }},
  "solution": "# Complete reference solution in Python\\ndef solution(...):\n    ..."
}}

Rules:
- Exactly 6 test cases. Ensure inputs contain diverse edge cases (e.g. empty, negative, max size).
- The 'schema' object MUST define 'params' (list of dicts with 'name' and 'type'), 'returns' (type), and 'judge' ("exact" or "any_order").
- Valid types: int, long, float, double, bool, string, char, int[], long[], float[], double[], bool[], string[], char[], int[][], string[][].
- Test case 'input' MUST be a dictionary mapping each parameter name to its JSON value (e.g. {{"arr": [1, 2, 3], "target": 5}}). DO NOT use a single string for input.
- Test case 'expected' MUST be a JSON string of the exact output (e.g. "5", "[1, 2]", "true", "\\"hello\\"").
- The function name MUST be exactly 'solution' in all languages. For Java, it MUST be a static method inside a class named 'Solution'.
- The 'starter_codes' MUST ONLY contain the function signature and 'pass'/'return'. DO NOT include the implementation. Provide starter code for Python, C++, and Java using the exact types from your schema.
- Exactly 3 MCQs covering System Design, DBMS, and OOP concepts. Provide exactly 4 options and detailed explanations.
- The solution must be syntactically valid Python.
- The solution MUST pass all 6 test cases.
"""


def _format_challenge_display(c: dict) -> str:
    lines = [
        f"## 🧩 {c.get('title', 'Challenge')}",
        f"**Difficulty:** {c.get('difficulty', '').capitalize()}  |  **Topic:** {c.get('topic', '')}",
        "",
        c.get("description", ""),
        "",
        "**Constraints:**",
    ]
    for constraint in c.get("constraints", []):
        lines.append(f"  - {constraint}")
    lines += ["", "**Examples:**"]
    for ex in c.get("examples", []):
        lines.append(f"  Input: `{ex.get('input')}`  →  Output: `{ex.get('output')}`")
        if ex.get("explanation"):
            lines.append(f"  _{ex['explanation']}_")
    lines += ["", "```", c.get("starter_code", "# write your solution here"), "```"]
    return "\n".join(lines)


def _parse_json_safe(text) -> Optional[dict]:
    if isinstance(text, dict):
        return text
    if not isinstance(text, str):
        return None
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]+\}", text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return None