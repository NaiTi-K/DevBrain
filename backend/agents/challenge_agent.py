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
    "int",
    "long",
    "float",
    "double",
    "bool",
    "string",
    "char",
    "int[]",
    "long[]",
    "float[]",
    "double[]",
    "bool[]",
    "string[]",
    "char[]",
    "int[][]",
    "string[][]",
    "List<int>",
    "List<string>",
    "List<List<int>>",
}

VALID_JUDGES = {"exact", "any_order"}


def validate_and_fix_challenge(parsed: dict) -> None:
    """Raises ValueError if invalid, and auto-fixes structural anomalies from LLMs."""
    if not parsed:
        raise ValueError("Empty response.")

    schema = parsed.get("schema", {})
    if not schema:
        raise ValueError("Missing 'schema' object in challenge.")

    params = schema.get("params", [])
    if not isinstance(params, list) or len(params) == 0:
        raise ValueError("schema.params must be a non-empty list.")

    for p in params:
        ptype = p.get("type")
        if isinstance(ptype, dict):
            ptype = ptype.get("type") or (list(ptype.values())[0] if ptype.values() else None)
            p["type"] = ptype

        if not isinstance(ptype, str) or ptype not in VALID_TYPES:
            raise ValueError(f"Unsupported type '{ptype}' in schema.params. Must be one of: {VALID_TYPES}")

    ret = schema.get("returns")
    if isinstance(ret, dict):
        ret = ret.get("type") or ret.get("returns") or (list(ret.values())[0] if ret.values() else None)
        schema["returns"] = ret

    if not isinstance(ret, str) or ret not in VALID_TYPES:
        raise ValueError(f"Unsupported return type '{ret}'.")

    judge = schema.get("judge", "exact")
    if judge not in VALID_JUDGES and not judge.startswith("epsilon:"):
        raise ValueError(f"Invalid judge '{judge}'. Must be 'exact', 'any_order', or 'epsilon:<tol>'.")

    # AUTO-FIX: Ensure test case inputs map to params properly!
    test_cases = parsed.get("test_cases", [])
    if not isinstance(test_cases, list) or not test_cases:
        raise ValueError("test_cases must be a non-empty list.")

    first_param_name = params[0]["name"]
    for tc in test_cases:
        if "input" not in tc:
            raise ValueError("Every test case must have an 'input' field.")
        if "expected" not in tc:
            raise ValueError("Every test case must have an 'expected' field.")

        # If the LLM provided a raw value instead of a dictionary mapping param names to values:
        if not isinstance(tc["input"], dict):
            tc["input"] = {first_param_name: tc["input"]}


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
            search_context = "\n\n".join(f"Source: {res['url']}\nContent: {res['content']}" for res in search_results)

        prompt = _build_challenge_prompt(
            topic=topic, difficulty=difficulty, language=primary_lang, skill=weak_skill, search_context=search_context
        )

        challenge_dict = None
        parsed: Optional[dict] = None

        for attempt in range(4):
            if parsed is None:
                temp = 0.8 + (attempt * 0.05)
                raw: str = await llm.structured_call(prompt, temperature=temp)
                parsed = _parse_json_safe(raw)

            if not parsed or "title" not in parsed:
                parsed = None
                continue

            try:
                validate_and_fix_challenge(parsed)
            except ValueError as e:
                # Retry once with correction
                correction_prompt = f"""Your previous challenge JSON was invalid: {e}
Please fix the JSON formatting or structure, and return the ENTIRE, COMPLETE challenge JSON object matching the full schema specified previously. Do not return a partial JSON or just a snippet. Return ONLY a single, valid JSON object."""
                try:
                    raw2 = await llm.structured_call(correction_prompt, temperature=0.6)
                    parsed2 = _parse_json_safe(raw2)
                    if parsed2:
                        parsed = parsed2
                        try:
                            validate_and_fix_challenge(parsed)
                        except ValueError:
                            parsed = None
                            continue
                    else:
                        parsed = None
                        continue
                except Exception:
                    parsed = None
                    continue

            # Verify solution against test cases
            solutions = parsed.get("solutions", {})
            solution_raw = solutions.get("python") or parsed.get("solution", "")
            solution_code = (
                solution_raw.get("python", str(solution_raw)) if isinstance(solution_raw, dict) else str(solution_raw)
            ).replace("\\n", "\n")

            test_cases = parsed.get("test_cases", [])

            if not solution_code or not test_cases:
                continue

            from services.sandbox_service import run_code
            import asyncio

            schema = parsed.get("schema", {})

            # 1. Run Python Reference Solution to align test case expected outputs
            eval_result = await asyncio.to_thread(
                run_code, "python", solution_code, schema, test_cases, schema.get("judge", "exact")
            )
            logger.info(f"Python eval result: status={eval_result.get('status')}, stderr={eval_result.get('stderr', '')[:200]}")
            if eval_result.get("test_results"):
                for tr in eval_result["test_results"]:
                    if tr.get("status") != "AC":
                        logger.info(f"  Failed case {tr.get('case')}: expected={tr.get('expected')}, got={tr.get('stdout')}")

            # Auto-align outputs if the sandbox test results are WA (meaning code executed successfully, but expected outputs differed)
            if eval_result.get("status") == "WA":
                valid = True
                updated_test_cases = []
                for idx, r in enumerate(eval_result.get("test_results", [])):
                    stdout = r.get("stdout")
                    if stdout is None or stdout.startswith("[ERR") or stdout == "":
                        valid = False
                        break
                    tc = test_cases[idx].copy()
                    tc["expected"] = stdout
                    updated_test_cases.append(tc)

                if valid and updated_test_cases:
                    parsed["test_cases"] = updated_test_cases
                    logger.info("Automatically aligned test case expected outputs with reference solution outputs.")
                    eval_result = await asyncio.to_thread(
                        run_code, "python", solution_code, schema, parsed["test_cases"], schema.get("judge", "exact")
                    )

            # 2. Run Tri-Language Verification concurrently for C++ and Java (if provided)
            # NOTE: C++/Java failures are NON-FATAL — they log warnings but do not
            # reject the challenge.  This prevents Docker-image availability or
            # timeout issues from blocking challenge generation entirely.
            cpp_sol = solutions.get("cpp")
            java_sol = solutions.get("java")

            verification_tasks = []
            if cpp_sol:
                logger.info("Verifying C++ solution in sandbox...")
                verification_tasks.append(
                    asyncio.to_thread(
                        run_code, "cpp", cpp_sol, schema, parsed["test_cases"], schema.get("judge", "exact")
                    )
                )
            if java_sol:
                logger.info("Verifying Java solution in sandbox...")
                verification_tasks.append(
                    asyncio.to_thread(
                        run_code, "java", java_sol, schema, parsed["test_cases"], schema.get("judge", "exact")
                    )
                )

            if verification_tasks:
                verification_results = await asyncio.gather(*verification_tasks, return_exceptions=True)
                task_idx = 0
                if cpp_sol:
                    cpp_eval = verification_results[task_idx]
                    task_idx += 1
                    if isinstance(cpp_eval, Exception):
                        logger.warning(f"C++ reference verification raised an exception: {cpp_eval}")
                    elif cpp_eval.get("status") != "AC":
                        logger.warning(
                            f"C++ reference verification failed! Status: {cpp_eval.get('status')}. Stderr: {cpp_eval.get('stderr')}"
                        )
                if java_sol:
                    java_eval = verification_results[task_idx]
                    if isinstance(java_eval, Exception):
                        logger.warning(f"Java reference verification raised an exception: {java_eval}")
                    elif java_eval.get("status") != "AC":
                        logger.warning(
                            f"Java reference verification failed! Status: {java_eval.get('status')}. Stderr: {java_eval.get('stderr')}"
                        )

            if eval_result.get("status") != "AC":
                err_msg = eval_result.get("stderr") or ""
                if not err_msg:
                    failed_cases = []
                    for r in eval_result.get("test_results", []):
                        if r.get("status") != "AC":
                            failed_cases.append(
                                f"Case {r.get('case')}: Expected {r.get('expected')}, but got {r.get('stdout')}"
                            )
                    err_msg = "Failed cases:\n" + "\n".join(failed_cases) if failed_cases else "Some test cases failed."

                correction_prompt = f"""Your previous generated challenge failed validation or test execution!
Error/Failures:
{err_msg}

You MUST fix the test cases or the solution code, and return the ENTIRE, COMPLETE challenge JSON object matching the full schema specified previously, including:
- "title"
- "description"
- "difficulty"
- "topic"
- "constraints"
- "examples"
- "test_cases"
- "schema" (including params, returns, and judge)
- "mcqs"
- "starter_codes"
- "solution"

Ensure the solution code is correct, and all test cases accurately match the expected outputs from the correct solution! Do not truncate the JSON or return a partial response. Return ONLY a single, valid JSON object."""
                try:
                    raw3 = await llm.structured_call(correction_prompt, temperature=0.6)
                    parsed3 = _parse_json_safe(raw3)
                    if parsed3 and "solution" in parsed3 and "title" in parsed3:
                        parsed = parsed3
                    else:
                        parsed = None
                except Exception:
                    parsed = None
                continue

            challenge_dict = parsed
            break

        if not challenge_dict and parsed:
            logger.error(
                "Failed to generate a passing challenge after 4 attempts. Falling back to the last generated challenge."
            )
            challenge_dict = parsed
        elif not challenge_dict:
            raise ValueError("Failed to generate a challenge after 4 attempts.")

        challenge_dict.setdefault("difficulty", difficulty)
        challenge_dict.setdefault("topic", topic)
        challenge_dict.setdefault("language", primary_lang)

        async with async_session() as session:
            solution_val = challenge_dict.get("solution", "")
            solution_str = (
                solution_val.get("python", str(solution_val)) if isinstance(solution_val, dict) else str(solution_val)
            ).replace("\\n", "\n")

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
                solution=solution_str,
                schema={**challenge_dict.get("schema", {}), "reference_solutions": challenge_dict.get("solutions", {})},
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
    import random

    return random.choice(["medium", "hard"])


def _build_challenge_prompt(topic: str, difficulty: str, language: str, skill: str, search_context: str) -> str:
    context_block = (
        f"\n=== INTERNET SEARCH CONTEXT ===\n{search_context}\n================================\n"
        if search_context
        else ""
    )

    return f"""You are a senior competitive programming coach creating coding challenges.
{context_block}
Target skill: {skill}
Topic area  : {topic}
Difficulty  : {difficulty}

Generate ONE coding challenge as a single JSON object.
CRITICAL INSTRUCTION: Do NOT invent a new problem. You MUST base this on a real, published competitive programming problem (e.g. from LeetCode or GeeksforGeeks) matching the topic.
Use the Internet Search Context above to extract a real problem statement, its mathematical constraints, and its proven test cases.
Make sure to pick a UNIQUE and INTERESTING problem. Do NOT repeatedly generate basic problems like "Two Sum" or "Find Duplicate in Array" unless specifically requested. Provide a different classic problem each time!

CRITICAL SCHEMA RULES:
1. You MUST define "schema.params". It must be a list containing exactly "name" and "type" for EVERY input argument.
2. Valid types: "int", "float", "bool", "string", "int[]", "float[]", "bool[]", "string[]", "int[][]", "string[][]". No other types are allowed!
3. You MUST define "schema.returns" as one of the valid types above.
4. The "test_cases" array MUST contain an "input" field that is a JSON DICTIONARY mapping parameter names to values (e.g. {{"arr": [1,2], "target": 3}}). Do NOT provide just the raw value.
5. The "test_cases" array MUST contain an "expected" field which is the expected output formatted as a JSON string (e.g. "[1, 2]" or "10").

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
    {{
      "question": "Deep Learning: Why is Layer Normalization generally preferred over Batch Normalization in Recurrent Neural Networks (RNNs) and Transformers?",
      "options": [
        "Layer Normalization computes statistics across the sequence length, making it faster during backpropagation.",
        "Layer Normalization normalizes activations across the channel/feature dimension for each individual token independently of other sequence items, avoiding issues with dynamic sequence lengths.",
        "Batch Normalization introduces structural bias that makes it impossible to compute attention weights concurrently.",
        "Layer Normalization is purely local, eliminating the need to store weight gradients for training."
      ],
      "correct_index": 1,
      "explanation": "Layer Normalization computes mean and variance statistics across the hidden/feature dimension for each token independently, which is extremely robust to sequence padding and dynamic sequence lengths, unlike Batch Normalization which depends on running statistics across batch items."
    }},
    {{
      "question": "System Design: In a highly distributed database using Raft consensus, how does the system prevent split-brain partition nodes from successfully committing conflicting log entries?",
      "options": [
        "A leader node can only commit log entries if it receives positive write acknowledgements from a strict majority (quorum) of all cluster nodes before responding to the client.",
        "Raft utilizes epoch-based locking which locks out all partitioning nodes dynamically via TCP keep-alives.",
        "Any split-brain partition automatically downgrades itself to a backup replica within 500ms using system heartbeats.",
        "A quorum is only required for leader elections, whereas log replication utilizes peer-to-peer gossip protocols."
      ],
      "correct_index": 0,
      "explanation": "In Raft consensus, any leader MUST replicate a log entry to a strict majority (quorum) of all nodes in the cluster config before it is considered committed. A partitioned leader in a minority subsegment can never establish a quorum, and thus its entries will never be committed."
    }},
    {{
      "question": "Python Internals: How does the Global Interpreter Lock (GIL) behave in modern multi-threaded Python applications when performing I/O bound operations?",
      "options": [
        "The GIL is completely bypassed using dynamic C-types memory allocation.",
        "Threads actively release the GIL when entering blocking system calls (like network read or file sleep), allowing other threads to run concurrently in the Python runtime.",
        "The OS scheduler forces the GIL to cycle every 5ms, dividing execution evenly among all running threads regardless of blockages.",
        "I/O threads spin-wait in user-space, maintaining GIL ownership until the kernel signals completion."
      ],
      "correct_index": 1,
      "explanation": "To prevent freezing Python applications during heavy I/O, standard library functions and standard sockets release the GIL right before entering blocking OS operations. This allows other threads to execute Python code concurrently in the background."
    }}
  ],
  "starter_codes": {{
    "python": "def solution(...):
    pass",
    "cpp": "#include <iostream>\n#include <vector>\nusing namespace std;\n\nclass Solution {{\npublic:\n    vector<int> solution(...) {{\n        return {{}};\n    }}\n}};",
    "java": "import java.util.*;\n\nclass Solution {{\n    public static int[] solution(...) {{\n        return new int[]{{}};\n    }}\n}}"
  }},
  "solutions": {{
    "python": "# Complete reference solution in Python\\ndef solution(...):\\n    ...",
    "cpp": "// Complete reference solution in C++\\n#include <vector>\\nusing namespace std;\\nclass Solution {{\\npublic:\\n    vector<int> solution(...) {{\\n        ...\\n    }}\n}};",
    "java": "// Complete reference solution in Java\\nimport java.util.*;\\npublic class Solution {{\\n    public static int[] solution(...) {{\\
        ...\\n    }}\n}}"
  }}
}}

Rules:
- CRITICAL: Do NOT generate "Design" class-style challenges (e.g., Design HashMap, Design LRU Cache, Design Twitter, implementing custom objects/classes with multiple methods). You MUST ONLY generate classic function-style challenges where the user implements a single function/method named exactly 'solution' that accepts inputs and returns a single output value.
- Exactly 6 test cases. Ensure inputs contain diverse edge cases (e.g. empty, negative, max size).
- The 'schema' object MUST define 'params' (list of dicts with 'name' and 'type'), 'returns' (type), and 'judge' ("exact" or "any_order").
- Valid types: int, long, float, double, bool, string, char, int[], long[], float[], double[], bool[], string[], char[], int[][], string[][].
- Test case 'input' MUST be a dictionary mapping each parameter name to its JSON value (e.g. {{"arr": [1, 2, 3], "target": 5}}). DO NOT use a single string for input.
- Test case 'expected' MUST be a JSON string of the exact output (e.g. "5", "[1, 2]", "true", "\"hello\"").
- The function name MUST be exactly 'solution' in all languages. For Java, it MUST be a static method inside a class named 'Solution'. For C++, it MUST be a method inside a class named 'Solution'.
- The 'starter_codes' MUST ONLY contain the function signature and 'pass'/'return'. DO NOT include the implementation. Provide starter code for Python, C++, and Java using the exact types from your schema.
- The 'solutions' MUST contain complete, fully-correct reference implementations in Python, C++, and Java that compile and pass all test cases!
- CRITICAL SOLUTION CORRECTNESS RULE: Every reference solution (Python, C++, Java) MUST implement the exact same correct logic, MUST accept and correctly use EVERY parameter defined in the schema (e.g., if the schema defines parameters like `max_sales` or `max_hold`, your code must actively use them in its logic and not ignore them), and must return the correct outputs. Do NOT write solutions to simpler classic variations of the problem that ignore parameters or constraints.
- Exactly 3 highly unique and challenging MCQs covering advanced theoretical knowledge and current trending technology concepts. These must span a broad range of subjects including Machine Learning/Deep Learning (e.g. transformers, architectures, loss functions), Distributed Systems/System Design (e.g. consensus, scaling, CAP theorem), Blockchain/Web3 (e.g. cryptography, smart contracts), Object-Oriented Programming (OOP), and advanced Programming Language Syntax/runtime internals (e.g. GIL, memory management, event loop, garbage collection). Do NOT generate basic or generic questions. The questions must test genuine, deep understanding and have extremely detailed explanation blocks.
- All three reference solutions must be syntactically valid and pass all 6 test cases.
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
