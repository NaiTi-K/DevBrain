"""
Profile Engine — deterministic GitHub portfolio analysis pipeline.

Pipeline
--------
  raw github_service output
    → classify skills / frameworks / practices
    → detect strengths & gaps (evidence-backed)
    → score engineering maturity
    → rank priority repos for improvement
    → render Markdown report (no LLM required)

The LLM layer (github_analyzer) may optionally polish the narrative;
all facts originate here.
"""

from __future__ import annotations

from typing import Any

# ── Thresholds (shared with roadmap_engine) ───────────────────────────────
MIN_MEANINGFUL_SKILL = 0.05
MASTERED_THRESHOLD = 0.70
PROFICIENT_THRESHOLD = 0.45

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _meaningful_skills(skills: dict[str, float]) -> list[tuple[str, float]]:
    return sorted(
        [(lang, score) for lang, score in skills.items() if score >= MIN_MEANINGFUL_SKILL],
        key=lambda x: x[1],
        reverse=True,
    )


def _skill_tier(score: float) -> str:
    if score >= MASTERED_THRESHOLD:
        return "mastered"
    if score >= PROFICIENT_THRESHOLD:
        return "proficient"
    if score >= 0.20:
        return "learning"
    return "exposure"


def _complexity_label(avg_cc: float) -> str:
    if avg_cc <= 5:
        return "clean"
    if avg_cc <= 10:
        return "moderate"
    if avg_cc <= 20:
        return "high"
    return "risky"


def compute_maturity_score(ep: dict) -> float:
    """Weighted engineering maturity on [0, 1]."""
    cicd = 1.0 if ep.get("has_cicd") else 0.0
    test = float(ep.get("test_signal", 0.0))
    commits = float(ep.get("commit_quality", 0.0))
    avg_cc = float(ep.get("avg_complexity", 0.0))
    complexity = max(0.0, 1.0 - (avg_cc / 25.0))  # 25+ CC → 0

    return round(cicd * 0.30 + test * 0.30 + commits * 0.25 + complexity * 0.15, 4)


def compute_primary_stack(
    skills: dict[str, float],
    frameworks: dict[str, float],
) -> dict[str, Any]:
    langs = _meaningful_skills(skills)
    top_langs = [lang for lang, _ in langs[:3]]
    top_fws = sorted(frameworks, key=lambda f: frameworks[f], reverse=True)[:6]
    stack_label = " / ".join(top_langs[:2]) if top_langs else "Unknown"
    if top_fws:
        stack_label += f" + {', '.join(top_fws[:3])}"
    return {
        "languages": top_langs,
        "frameworks": top_fws,
        "label": stack_label,
    }


def compute_strengths(
    skills: dict[str, float],
    frameworks: dict[str, float],
    repo_highlights: list[dict],
    ep: dict,
) -> list[dict]:
    """Evidence-backed strength records."""
    strengths: list[dict] = []

    for lang, score in _meaningful_skills(skills)[:5]:
        if score >= PROFICIENT_THRESHOLD:
            strengths.append(
                {
                    "category": "language",
                    "name": lang,
                    "score": score,
                    "tier": _skill_tier(score),
                    "evidence": f"Language score {score:.0%} across analyzed repos",
                }
            )

    for fw, score in sorted(frameworks.items(), key=lambda x: x[1], reverse=True):
        if score >= 0.70:
            repos_using = [r["name"] for r in repo_highlights if fw in (r.get("frameworks") or [])]
            strengths.append(
                {
                    "category": "framework",
                    "name": fw,
                    "score": score,
                    "tier": "proficient",
                    "evidence": (
                        f"Detected in {', '.join(repos_using)}" if repos_using else "Found in dependency manifests"
                    ),
                }
            )

    for repo in repo_highlights:
        name = repo.get("name", "?")
        flags: list[str] = []
        if repo.get("has_cicd"):
            flags.append("CI/CD")
        if repo.get("has_tests"):
            flags.append("tests")
        if repo.get("stars", 0) >= 5:
            flags.append(f"{repo['stars']} stars")
        if flags:
            strengths.append(
                {
                    "category": "repo",
                    "name": name,
                    "score": 1.0,
                    "tier": "standout",
                    "evidence": f"{name}: {', '.join(flags)}",
                }
            )

    if ep.get("has_cicd"):
        strengths.append(
            {
                "category": "practice",
                "name": "CI/CD",
                "score": 1.0,
                "tier": "proficient",
                "evidence": "At least one repo has GitHub Actions or equivalent",
            }
        )

    return strengths


def compute_gaps(
    skills: dict[str, float],
    frameworks: dict[str, float],
    ep: dict,
    repo_highlights: list[dict],
) -> list[dict]:
    """Ranked gap list — practice, per-repo, and stack holes."""
    gaps: list[dict] = []

    if not ep.get("has_cicd"):
        gaps.append(
            {
                "id": "practice_cicd",
                "category": "practice",
                "severity": "critical",
                "title": "No CI/CD pipeline detected",
                "detail": "None of your top repos run automated builds or tests on push.",
                "action": "Add GitHub Actions workflow to your most active repo",
            }
        )

    test_signal = float(ep.get("test_signal", 0.0))
    if test_signal < 0.4:
        sev = "critical" if test_signal < 0.2 else "high"
        gaps.append(
            {
                "id": "practice_testing",
                "category": "practice",
                "severity": sev,
                "title": "Weak automated testing signal",
                "detail": f"Only {test_signal:.0%} of top repos expose a tests/ directory.",
                "action": "Add pytest or Jest tests to a production repo",
            }
        )

    commit_q = float(ep.get("commit_quality", 0.0))
    if commit_q < 0.35:
        gaps.append(
            {
                "id": "practice_commits",
                "category": "practice",
                "severity": "high",
                "title": "Low commit message hygiene",
                "detail": (
                    f"Commit quality score {commit_q:.0%} — messages lack conventional format or descriptive detail."
                ),
                "action": "Adopt Conventional Commits (feat:, fix:, chore:) with meaningful bodies",
            }
        )

    avg_cc = float(ep.get("avg_complexity", 0.0))
    if avg_cc > 10:
        gaps.append(
            {
                "id": "practice_complexity",
                "category": "practice",
                "severity": "high" if avg_cc > 20 else "medium",
                "title": f"High cyclomatic complexity ({avg_cc:.1f})",
                "detail": f"Average Python CC is {_complexity_label(avg_cc)} (target ≤10).",
                "action": "Extract functions, reduce nesting in your largest Python modules",
            }
        )

    for repo in repo_highlights:
        name = repo.get("name", "?")
        missing: list[str] = []
        if not repo.get("has_tests"):
            missing.append("tests")
        if not repo.get("has_cicd"):
            missing.append("CI/CD")
        if not repo.get("description"):
            missing.append("README/description")
        if not (repo.get("frameworks") or []):
            missing.append("declared dependencies")

        if missing:
            gaps.append(
                {
                    "id": f"repo_{name}",
                    "category": "repo",
                    "severity": "high" if len(missing) >= 2 else "medium",
                    "title": f"{name} lacks {', '.join(missing)}",
                    "detail": (f"{name} ({repo.get('primary_language', '?')}) — {repo.get('stars', 0)} stars"),
                    "action": f"Harden {name}: add {missing[0]} first",
                    "repo": name,
                }
            )

    langs = _meaningful_skills(skills)
    if langs:
        primary = langs[0][0]
        for lang, score in langs[3:]:
            if score < 0.15 and lang not in (primary,):
                gaps.append(
                    {
                        "id": f"lang_{lang.lower()}",
                        "category": "language",
                        "severity": "low",
                        "title": f"Minimal {lang} footprint",
                        "detail": f"{lang} score {score:.0%} vs primary {primary} {langs[0][1]:.0%}",
                        "action": f"Either deepen {lang} or remove dead code paths using it",
                    }
                )

    gaps.sort(key=lambda g: SEVERITY_ORDER.get(g["severity"], 9))
    return gaps


def compute_priority_repos(repo_highlights: list[dict]) -> list[dict]:
    """
    Repos ranked by improvement ROI (most gaps + still meaningful projects).
    """
    scored: list[tuple[int, dict]] = []
    for repo in repo_highlights:
        penalty = 0
        if not repo.get("has_tests"):
            penalty += 3
        if not repo.get("has_cicd"):
            penalty += 2
        if not repo.get("description"):
            penalty += 1
        if not (repo.get("frameworks") or []):
            penalty += 1
        # Prefer repos with some activity
        penalty -= min(repo.get("stars", 0), 5)
        scored.append((penalty, repo))

    scored.sort(key=lambda x: x[0], reverse=True)
    result: list[dict] = []
    for priority, (score, repo) in enumerate(scored, start=1):
        actions: list[str] = []
        if not repo.get("has_tests"):
            actions.append("add test suite")
        if not repo.get("has_cicd"):
            actions.append("add CI/CD workflow")
        if not repo.get("description"):
            actions.append("write README")
        result.append(
            {
                "priority": priority,
                "name": repo.get("name"),
                "language": repo.get("primary_language"),
                "stars": repo.get("stars", 0),
                "frameworks": repo.get("frameworks") or [],
                "improvement_score": score,
                "recommended_actions": actions,
            }
        )
    return result


def build_analysis_report(profile_data: dict, github_username: str) -> dict:
    """
    Main entry: convert github_service output → structured analysis report.
    """
    skills = profile_data.get("skills", {})
    frameworks = profile_data.get("frameworks", {})
    ep = profile_data.get("engineering_practices", {})
    repo_highlights = profile_data.get("repo_highlights", [])
    sample_commits = profile_data.get("sample_commits", [])

    primary_stack = compute_primary_stack(skills, frameworks)
    strengths = compute_strengths(skills, frameworks, repo_highlights, ep)
    gaps = compute_gaps(skills, frameworks, ep, repo_highlights)
    priority_repos = compute_priority_repos(repo_highlights)
    maturity = compute_maturity_score(ep)

    skill_tiers = {lang: _skill_tier(score) for lang, score in skills.items() if score >= MIN_MEANINGFUL_SKILL}

    return {
        "github_username": github_username,
        "repo_count": profile_data.get("repo_count", 0),
        "deep_scanned_names": profile_data.get("deep_scanned_names", []),
        "repo_stats": profile_data.get("repo_stats", {}),
        "primary_stack": primary_stack,
        "skill_tiers": skill_tiers,
        "skills": skills,
        "frameworks": frameworks,
        "engineering_practices": ep,
        "maturity_score": maturity,
        "maturity_label": (
            "senior-ready"
            if maturity >= 0.75
            else "mid-level"
            if maturity >= 0.50
            else "junior"
            if maturity >= 0.30
            else "early-career"
        ),
        "strengths": strengths,
        "gaps": gaps,
        "priority_repos": priority_repos,
        "repo_highlights": repo_highlights,
        "sample_commits": sample_commits[:10],
        "used_github_token": profile_data.get("used_github_token", False),
    }


def render_analysis_markdown(report: dict) -> str:
    """Deterministic, evidence-based Markdown — primary user-facing summary."""
    username = report["github_username"]
    repo_count = report["repo_count"]
    deep_scanned = report.get("deep_scanned_names") or []
    repo_stats = report.get("repo_stats") or {}
    stack = report["primary_stack"]["label"]
    maturity = report["maturity_score"]
    maturity_label = report["maturity_label"]

    # Strengths section
    lang_strengths = [s for s in report["strengths"] if s["category"] == "language"][:4]
    fw_strengths = [s for s in report["strengths"] if s["category"] == "framework"][:5]
    repo_strengths = [s for s in report["strengths"] if s["category"] == "repo"][:3]

    strength_lines: list[str] = []
    if lang_strengths:
        langs = ", ".join(f"**{s['name']}** ({s['score']:.0%}, {s['tier']})" for s in lang_strengths)
        strength_lines.append(f"- **Languages:** {langs}")
    if fw_strengths:
        fws = ", ".join(f"**{s['name']}**" for s in fw_strengths)
        strength_lines.append(f"- **Stack:** {fws}")
    for s in repo_strengths:
        strength_lines.append(f"- **{s['evidence']}**")

    for repo in report["repo_highlights"][:4]:
        fw = ", ".join(repo.get("frameworks") or []) or "no manifest detected"
        strength_lines.append(f"- `{repo.get('name')}` ({repo.get('primary_language')}, {repo.get('stars', 0)}★): {fw}")

    # Practices section
    ep = report["engineering_practices"]
    commits = report.get("sample_commits") or []
    commit_samples = "\n".join(f'  - "{c}"' for c in commits[:4]) or "  - (none fetched)"

    # Gaps section
    gap_lines = [f"- **[{g['severity'].upper()}]** {g['title']}: {g['action']}" for g in report["gaps"][:6]]

    # Roadmap focus
    priority = report["priority_repos"][0] if report["priority_repos"] else None
    if priority and priority.get("recommended_actions"):
        focus = (
            f"Start with **`{priority['name']}`** — "
            f"{priority['recommended_actions'][0]}, then "
            f"{priority['recommended_actions'][1] if len(priority['recommended_actions']) > 1 else 'document the project'}."
        )
    elif report["gaps"]:
        focus = report["gaps"][0]["action"]
    else:
        focus = f"Build a capstone project showcasing your {stack} stack with full CI/CD."

    inventory_note = ""
    if repo_stats:
        parts = [f"{repo_stats.get('analyzed_count', repo_count)} owned"]
        if repo_stats.get("private_count"):
            parts.append(f"{repo_stats['private_count']} private")
        if repo_stats.get("forks_skipped"):
            parts.append(f"{repo_stats['forks_skipped']} forks skipped")
        inventory_note = f" ({', '.join(parts)})"

    deep_scan_note = (
        f"**Deep-scanned ({len(deep_scanned)}):** " + ", ".join(f"`{n}`" for n in deep_scanned)
        if deep_scanned
        else "**Deep scan:** top repos by code size & recent activity"
    )

    return (
        f"### GitHub Analysis for @{username}\n\n"
        f"**Repos analyzed:** {repo_count}{inventory_note}  |  "
        f"{deep_scan_note}  |  "
        f"**Primary stack:** {stack}  |  "
        f"**Engineering maturity:** {maturity:.0%} ({maturity_label})\n\n"
        f"#### Technical Strengths & Stack\n"
        f"{chr(10).join(strength_lines) or '- Insufficient data — add a GitHub token and re-analyze.'}\n\n"
        f"#### Engineering Practices\n"
        f"- CI/CD: {'✅ detected' if ep.get('has_cicd') else '❌ missing'}\n"
        f"- Test signal: {ep.get('test_signal', 0):.0%} of top repos have test directories\n"
        f"- Commit hygiene: {ep.get('commit_quality', 0):.0%}\n"
        f"- Avg Python complexity: {ep.get('avg_complexity', 0):.1f} ({_complexity_label(float(ep.get('avg_complexity', 0)))})\n"
        f"- Sample commits:\n{commit_samples}\n\n"
        f"#### Core Weaknesses & Gaps\n"
        f"{chr(10).join(gap_lines) or '- No critical gaps detected — focus on depth and capstone projects.'}\n\n"
        f"#### Recommended Roadmap Focus\n"
        f"{focus}"
    )
