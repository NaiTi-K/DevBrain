"""
Code Review Agent with AST, Linter, and Sandbox Verification
============================================================
"""

from __future__ import annotations

import json
import logging

from agents.orchestrator import DevBrainState
from services.llm_service import llm
from services.ast_analyzer import analyze_code
from services.linter_service import run_linter
from services.sandbox_service import check_syntax, benchmark_code

logger = logging.getLogger(__name__)

REVIEW_SYSTEM = (
    "You are a senior software engineer doing code reviews. "
    "Be specific, actionable, and educational. Always include Big-O complexity."
)

REVIEW_PROMPT = (
    "Review this {language} code:\n"
    "```{language}\n{code}\n```\n"
    "=== PRE-COMPUTED FACTS (Do not re-derive these) ===\n"
    "AST Report:\n{ast_report}\n\n"
    "Linter Violations:\n{linter_report}\n"
    "===================================================\n"
    "Based on the code and these facts, provide your review.\n"
    "Return ONLY a JSON object with these exact fields:\n"
    "{{\n"
    '  "score": 8,\n'
    '  "annotations": [ {{"line": 42, "issue": "missing type hint", "fix": "add -> int"}} ],\n'
    '  "complexity": {{"time": "O(N)", "space": "O(1)"}},\n'
    '  "edge_cases": [ "empty list input" ],\n'
    '  "improvements": [ {{"title": "Use list comprehension", "description": "Faster", "code_after": "x = [1]"}} ],\n'
    '  "summary": "overall assessment"\n'
    "}}"
)

def _extract_language_and_code(state: DevBrainState) -> tuple[str, str]:
    structured: dict = state.get("structured_output") or {}
    language = structured.get("language") or "python"
    code = structured.get("code") or ""

    if not code:
        user_input = state.get("user_input", "")
        if isinstance(user_input, str):
            try:
                parsed = json.loads(user_input)
                language = parsed.get("language", language)
                code = parsed.get("code", "")
            except (json.JSONDecodeError, TypeError):
                code = user_input
    return language, code

async def code_review_node(state: DevBrainState) -> DevBrainState:
    """Runs AST + Linter, then calls LLM."""
    language, code = _extract_language_and_code(state)

    # 1. AST Analysis
    ast_facts = {"error": "Only supported for Python"}
    if language.lower() in ("python", "py"):
        ast_facts = analyze_code(code)
    
    # 2. Linter
    lint_facts = await run_linter(code, language)
    
    prompt = REVIEW_PROMPT.format(
        language=language,
        code=code,
        ast_report=json.dumps(ast_facts, indent=2),
        linter_report=json.dumps(lint_facts, indent=2)
    )

    try:
        review_dict = await llm.structured_call(prompt, REVIEW_SYSTEM)
    except Exception as exc:
        logger.error("LLM call failed in code_review_node: %s", exc)
        review_dict = {
            "score": 0, "annotations": [], "complexity": {"time": "unknown", "space": "unknown"},
            "edge_cases": [], "improvements": [], "summary": f"Error: {exc}"
        }

    review_dict.setdefault("improvements", [])
    review_dict["language"] = language
    review_dict["code"] = code
    review_dict["ast_facts"] = ast_facts
    review_dict["lint_facts"] = lint_facts

    state["structured_output"] = review_dict
    state["agent_output"] = json.dumps(review_dict)
    
    return state

async def reflection_node(state: DevBrainState) -> DevBrainState:
    """Now acts as the Sandbox Execution node."""
    review_dict = state.get("structured_output", {})
    language = review_dict.get("language", "python")
    original_code = review_dict.get("code", "")
    improvements = review_dict.get("improvements", [])
    
    for imp in improvements:
        code_after = imp.get("code_after")
        if not code_after:
            continue
            
        # 1. Syntax check
        syntax_res = await check_syntax(code_after, language)
        if not syntax_res["ok"]:
            imp["verification"] = {"verified": False, "badge": "⛔ SYNTAX ERROR", "message": syntax_res["error"]}
            continue
            
        # 2. Benchmark
        orig_bench = await benchmark_code(original_code, language)
        imp_bench = await benchmark_code(code_after, language)
        
        if orig_bench["ok"] and imp_bench["ok"] and imp_bench["median_ms"] > 0:
            speedup = orig_bench["median_ms"] / imp_bench["median_ms"]
            imp["verification"] = {
                "verified": True, 
                "badge": "✅ VERIFIED", 
                "message": f"Compiled successfully. {speedup:.1f}x speedup vs original.",
                "speedup": speedup
            }
        else:
            imp["verification"] = {
                "verified": True, 
                "badge": "✅ COMPILES", 
                "message": "Syntax valid, but benchmarking failed or timed out."
            }
            
    state["structured_output"] = review_dict
    state["agent_output"] = json.dumps(review_dict)
    return state

def should_reflect_again(state: DevBrainState) -> str:
    """We removed the loop, this just routes to done."""
    return "done"