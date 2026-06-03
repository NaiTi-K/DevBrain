"""
pre_analyzer.py
Static code analysis using Python's built-in re and ast modules only.
No external packages required.
Returns a dict of hints that ground the LLM review.
"""

import re
import ast
from typing import Optional


# ─── Language Detection ────────────────────────────────────────────────────────


def detect_language(code: str, language_hint: Optional[str] = None) -> str:
    """
    Detect the programming language of the code.
    Returns one of: 'python', 'cpp', 'java', 'unknown'
    """
    if language_hint:
        lang = language_hint.lower().strip()
        if lang in ("python", "py"):
            return "python"
        if lang in ("cpp", "c++", "c"):
            return "cpp"
        if lang in ("java",):
            return "java"

    # Fallback: pattern-based detection
    if re.search(r"#include\s*<|using namespace std|std::", code):
        return "cpp"
    if re.search(r"\bpublic class\b|\bimport java\.", code):
        return "java"
    if re.search(r"\bdef \w+\(|import \w+|from \w+ import", code):
        return "python"
    return "unknown"


# ─── Loop Nesting Analysis ─────────────────────────────────────────────────────


def count_max_loop_nesting(code: str, language: str) -> int:
    """
    Count the maximum depth of nested loops (for/while) in the code.
    Uses regex for C++/Java, ast for Python.
    Returns an integer (0 = no loops, 1 = single loop, 2 = nested, etc.)
    """
    if language == "python":
        try:
            tree = ast.parse(code)
            return _python_max_loop_depth(tree)
        except SyntaxError:
            pass  # Fall through to regex

    # Regex approach for C++, Java, and Python fallback
    return _regex_loop_depth(code)


def _python_max_loop_depth(node, current_depth: int = 0) -> int:
    """Walk Python AST to find max nesting depth of For/While nodes."""
    max_depth = current_depth
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.For, ast.While)):
            child_depth = _python_max_loop_depth(child, current_depth + 1)
            max_depth = max(max_depth, child_depth)
        else:
            child_depth = _python_max_loop_depth(child, current_depth)
            max_depth = max(max_depth, child_depth)
    return max_depth


def _regex_loop_depth(code: str) -> int:
    """
    Estimate max loop nesting via indentation of loop keywords.
    Works on C++, Java, Python.
    """
    loop_pattern = re.compile(r"^(\s*)(for|while)\s*[\(\s]", re.MULTILINE)
    matches = loop_pattern.findall(code)
    if not matches:
        return 0
    # Indentation levels suggest nesting
    indent_sizes = [len(indent) for indent, _ in matches]
    if not indent_sizes:
        return 0
    # Normalize: how many distinct nesting levels?
    unique_indents = sorted(set(indent_sizes))
    return len(unique_indents)


# ─── Recursion Detection ───────────────────────────────────────────────────────


def detect_recursion(code: str, language: str) -> bool:
    """
    Detect if any function calls itself (direct recursion).
    Returns True if recursion is likely present.
    """
    if language == "python":
        try:
            tree = ast.parse(code)
            return _python_detect_recursion(tree)
        except SyntaxError:
            pass

    # Regex fallback for all languages:
    # Find function/method names, then check if any of them appear in the body
    if language == "cpp":
        func_names = re.findall(r"\b(?:int|long|void|bool|string|double|auto|vector\s*<[^>]+>)\s+(\w+)\s*\(", code)
    elif language == "java":
        func_names = re.findall(r"\b(?:public|private|protected|static)(?:\s+\w+)+\s+(\w+)\s*\(", code)
    else:
        func_names = re.findall(r"^def\s+(\w+)\s*\(", code, re.MULTILINE)

    for name in func_names:
        if name in ("main", "Main", "__init__"):
            continue
        # Check if the function name appears more than once (definition + call)
        occurrences = len(re.findall(r"\b" + re.escape(name) + r"\b", code))
        if occurrences > 1:
            return True
    return False


def _python_detect_recursion(tree) -> bool:
    """Walk Python AST to find functions that call themselves."""
    func_defs = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in func_defs:
                # Find the enclosing function definition to see if it's the same name
                parent = _find_enclosing_function(tree, node)
                if parent and parent.name == node.func.id:
                    return True
    return False


def _find_enclosing_function(tree, target_node) -> Optional[ast.AST]:
    """Find the function definition containing the target node by traversing the tree."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for subnode in ast.walk(node):
                if subnode is target_node:
                    return node
    return None


# ─── Common Pattern Detection ─────────────────────────────────────────────────


def detect_patterns(code: str, language: str) -> dict:
    """
    Detect common algorithmic patterns and code features.
    Returns a dict of booleans.
    """
    patterns = {}

    # Sorting
    if language == "python":
        patterns["has_sort"] = bool(re.search(r"\bsort\b|\bsorted\b", code))
    elif language == "cpp":
        patterns["has_sort"] = bool(re.search(r"\bstd::sort\b|\bsort\(", code))
    elif language == "java":
        patterns["has_sort"] = bool(re.search(r"Arrays\.sort|Collections\.sort", code))
    else:
        patterns["has_sort"] = False

    # Hash map / set usage
    if language == "python":
        patterns["uses_hashmap"] = bool(re.search(r"\bdict\b|\bset\b|\{\s*\}|\{\s*[\'\"\w]", code))
    elif language == "cpp":
        patterns["uses_hashmap"] = bool(re.search(r"unordered_map|unordered_set|map<|set<", code))
    elif language == "java":
        patterns["uses_hashmap"] = bool(re.search(r"HashMap|HashSet|TreeMap|LinkedHashMap", code))
    else:
        patterns["uses_hashmap"] = False

    # Dynamic programming signals
    patterns["possible_dp"] = bool(re.search(r"\bdp\b|\bmemo\b|\bcache\b|\blookup\b", code, re.IGNORECASE))

    # Graph/tree signals
    patterns["graph_or_tree"] = bool(
        re.search(r"\bBFS\b|\bDFS\b|\bgraph\b|\badjacency\b|\bnode\b|\broot\b|\btree\b", code, re.IGNORECASE)
    )

    # Two pointer / sliding window
    patterns["two_pointer"] = bool(re.search(r"\bleft\b.*\bright\b|\bstart\b.*\bend\b|\bwindow\b", code, re.IGNORECASE))

    # Binary search
    patterns["binary_search"] = bool(re.search(r"\bmid\b|\bbinary.search\b|\blow\b.*\bhigh\b", code, re.IGNORECASE))

    return patterns


# ─── Code Metrics ─────────────────────────────────────────────────────────────


def get_code_metrics(code: str) -> dict:
    """
    Basic metrics: line count, blank line count, comment density.
    """
    lines = code.splitlines()
    total = len(lines)
    blank = sum(1 for line in lines if not line.strip())
    comments = sum(1 for line in lines if line.strip().startswith(("#", "//", "/*", "*", '"""', "'''")))
    return {
        "total_lines": total,
        "blank_lines": blank,
        "comment_lines": comments,
        "code_lines": total - blank - comments,
    }


# ─── Main Entry Point ──────────────────────────────────────────────────────────


def run_pre_analysis(code: str, language_hint: Optional[str] = None) -> dict:
    """
    Run all static analysis checks on the provided code.
    Returns a dict of hints to be injected into the LLM prompt.

    This is the ONLY function that review_routes.py should call from this module.
    """
    language = detect_language(code, language_hint)
    loop_depth = count_max_loop_nesting(code, language)
    has_recursion = detect_recursion(code, language)
    patterns = detect_patterns(code, language)
    metrics = get_code_metrics(code)

    return {
        "language": language,
        "loop_nesting_depth": loop_depth,
        "has_recursion": has_recursion,
        "has_sort": patterns.get("has_sort", False),
        "uses_hashmap": patterns.get("uses_hashmap", False),
        "possible_dp": patterns.get("possible_dp", False),
        "graph_or_tree": patterns.get("graph_or_tree", False),
        "two_pointer": patterns.get("two_pointer", False),
        "binary_search": patterns.get("binary_search", False),
        "total_lines": metrics["total_lines"],
        "code_lines": metrics["code_lines"],
        "comment_lines": metrics["comment_lines"],
    }
