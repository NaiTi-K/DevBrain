"""
prompts.py
Prompt templates for the Code Reviewer agent.
Contains:
  - SYSTEM_PROMPT: sets the LLM persona
  - REVIEW_TEMPLATE: the markdown template the LLM fills in
  - build_prompt(): assembles the final prompt from code + hints
"""


# ─── System Prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert code reviewer and senior software engineer
with deep knowledge of Python, C++, and Java. You have 15 years of experience
in competitive programming, system design, and production software engineering.

Your job is to review code and produce a structured, honest, and actionable review.
You always:
- Identify bugs that would cause wrong output or crashes
- Estimate time and space complexity from reading the code (step by step)
- Suggest a genuinely better algorithm only when one clearly exists
- Point out language-specific best practices
- Are direct and specific — you never give vague feedback like "improve variable names"
  without showing exactly what to rename and to what

You output ONLY the structured markdown review. No preamble. No "Sure, here is...".
Start directly with the first markdown section heading."""


# ─── Review Prompt Template ────────────────────────────────────────────────────
# This is what gets sent to the LLM.
# {placeholders} are filled in by build_prompt().

REVIEW_TEMPLATE = """## Code Review Request

**Language:** {language}
**Lines of code:** {code_lines}
**User context:** {user_context}

### Static Analysis Hints (use these to ground your complexity analysis)
- Maximum loop nesting depth detected: {loop_nesting_depth}
- Recursion detected: {has_recursion}
- Sorting operation present: {has_sort}
- Hash map / set usage detected: {uses_hashmap}
- Dynamic programming pattern signals: {possible_dp}
- Graph / Tree pattern signals: {graph_or_tree}
- Two-pointer / sliding window signals: {two_pointer}
- Binary search signals: {binary_search}

### Code to Review
```{language}
{code}
```

---

Write your review using EXACTLY the following sections in order.
Do not skip any section. Do not add extra sections.
Use the static analysis hints above to make your complexity analysis concrete.

---

## 🧩 What This Code Does
One short paragraph explaining what problem this code solves and what algorithm/approach it uses.
Be specific — name the algorithm (e.g. "sliding window", "BFS", "two-pointer").

---

## 🐛 Bugs & Correctness Issues

For each bug found, use this exact format:

### Bug [N]: [Short title]
**Severity:** 🔴 Critical / 🟡 Warning / 🔵 Info
**Location:** Line [X] or describe where
**Problem:** Explain precisely what is wrong and what input would trigger it.
**Fix:**
```{language}
// Show the corrected code here
```

If no bugs are found, write: "✅ No bugs detected. Logic appears correct."

---

## ⏱️ Time & Space Complexity

### Time Complexity
Walk through the code step by step and derive the Big-O.
Use the static hints above. Show your reasoning like this:
- Line X: outer loop runs N times → O(N)
- Line Y: inner operation → O(1) or O(log N) etc.
- **Overall Time Complexity: O(???)**

### Space Complexity
- Identify what extra memory is allocated
- **Overall Space Complexity: O(???)**

---

## 💡 Better Approach (only if one clearly exists)

If the current approach is already optimal, write:
"✅ Current approach is optimal for this problem."

Otherwise:
**Current:** [approach name] — [why it's suboptimal]
**Recommended:** [approach name]
**Why better:** [concrete reason with complexity comparison]
**Sketch:**
```{language}
// Show the key idea in pseudocode or real code (10-20 lines max)
```
**Complexity improvement:** [Current O(?)] → [Better O(?)]

---

## 🛠️ Code Quality Issues

For each quality issue, use this format:

### Quality Issue [N]: [Title]
**Type:** Naming / Readability / Structure / Error Handling / Magic Number
**Location:** Line [X]
**Issue:** [Specific description]
**Suggested fix:** [Concrete suggestion, not vague advice]

If code quality is good, write: "✅ Code quality is good."

---

## ✅ Language Best Practices ({language})

List 4-6 specific best practices for {language} and whether this code follows them.
Use checkboxes:

- [x] Practice that IS followed
- [ ] Practice that is NOT followed — brief note on what to do

Choose practices relevant to what this code actually does.
"""


# ─── Prompt Builder ────────────────────────────────────────────────────────────


def build_prompt(code: str, hints: dict, user_context: str = "") -> str:
    """
    Build the final prompt string from code and pre-analysis hints.
    This is the ONLY function review_routes.py should call from this module.

    Args:
        code: the raw source code string
        hints: dict returned by pre_analyzer.run_pre_analysis()
        user_context: optional string the user wrote about their code

    Returns:
        A complete prompt string ready to send to the Groq API.
    """
    language = hints.get("language", "unknown")
    if language == "unknown":
        language = "code"

    return REVIEW_TEMPLATE.format(
        language=language,
        code_lines=hints.get("code_lines", "?"),
        user_context=user_context.strip() if user_context else "No additional context provided.",
        loop_nesting_depth=hints.get("loop_nesting_depth", 0),
        has_recursion="Yes" if hints.get("has_recursion") else "No",
        has_sort="Yes" if hints.get("has_sort") else "No",
        uses_hashmap="Yes" if hints.get("uses_hashmap") else "No",
        possible_dp="Yes" if hints.get("possible_dp") else "No",
        graph_or_tree="Yes" if hints.get("graph_or_tree") else "No",
        two_pointer="Yes" if hints.get("two_pointer") else "No",
        binary_search="Yes" if hints.get("binary_search") else "No",
        code=code,
    )


# ─── Streaming Prompt (separate — never mix with above) ────────────────────────

STREAM_SYSTEM_PROMPT = """You are a senior software engineer reviewing code in real time.
Write a clear, beautiful markdown review. Be specific and actionable.
Output ONLY the review markdown. Start directly with the first heading."""

STREAM_TEMPLATE = """Review this {language} code:

```{language}
{code}
```

Context: {user_context}

Write a review with these sections:
## 🧩 What This Code Does
## 🐛 Bugs & Issues
## ⏱️ Complexity Analysis
## 💡 Improvements
## ✅ Best Practices
"""


def build_stream_prompt(code: str, language: str, user_context: str = "") -> str:
    """
    Build the simpler prompt used by the streaming endpoint.
    Does NOT require pre-analysis hints.
    Does NOT produce JSON.
    """
    return STREAM_TEMPLATE.format(
        language=language or "code",
        code=code,
        user_context=user_context.strip() if user_context else "None",
    )
