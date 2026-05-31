"""
Roadmap Engine — deterministic 6-week plan from analysis_report.

Algorithm
---------
  1. Load structured analysis_report (from profile_engine).
  2. Map target role → required skill/practice dimensions.
  3. Diff profile vs role requirements → ranked learning objectives.
  4. Allocate objectives across 6 weeks:
       W1–2 : Engineering practice fixes on priority repos
       W3–4 : Role-specific skill gaps (skip mastered topics)
       W5   : Integration project on strongest repo
       W6   : Capstone + deploy + portfolio polish
  5. Each week gets focus, topics, project_idea, reason — all evidence-linked.

LLM may optionally polish copy; week structure is locked.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from services.profile_engine import MASTERED_THRESHOLD

logger = logging.getLogger(__name__)

# ── Role requirement definitions ───────────────────────────────────────────
# Each role lists skills/frameworks/practices with minimum target scores.

ROLE_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "Full Stack Engineer": {
        "languages": {"TypeScript": 0.45, "JavaScript": 0.35, "Python": 0.25},
        "frameworks": {"React": 0.5, "Node.js": 0.4, "Express": 0.35},
        "practices": {"test_signal": 0.4, "has_cicd": True, "commit_quality": 0.35},
        "topics_pool": [
            ("fullstack_integration", "Full-stack feature slice", [
                "Connect React frontend to REST API",
                "Shared TypeScript types between client/server",
                "Error handling across the stack",
            ]),
            ("database_layer", "Database & persistence", [
                "Schema design and migrations",
                "ORM/query patterns (SQLAlchemy or Prisma)",
                "Indexing and basic query optimization",
            ]),
            ("auth", "Authentication & authorization", [
                "JWT or session-based auth",
                "Protected routes on frontend and backend",
                "Role-based access patterns",
            ]),
            ("deployment", "Production deployment", [
                "Docker multi-stage builds",
                "Environment configuration",
                "Health checks and logging",
            ]),
            ("testing_fullstack", "End-to-end testing", [
                "API integration tests",
                "Component tests with React Testing Library",
                "CI pipeline running all test layers",
            ]),
        ],
    },
    "Backend Engineer": {
        "languages": {"Python": 0.50, "Go": 0.25, "JavaScript": 0.20},
        "frameworks": {"FastAPI": 0.45, "Django": 0.40, "SQLAlchemy": 0.35},
        "practices": {"test_signal": 0.5, "has_cicd": True, "commit_quality": 0.40},
        "topics_pool": [
            ("api_design", "API design & versioning", [
                "REST resource modeling", "Input validation with Pydantic",
                "Pagination, filtering, error contracts",
            ]),
            ("system_design", "System design fundamentals", [
                "Caching strategies (Redis)", "Message queues overview",
                "Rate limiting and idempotency",
            ]),
            ("database_backend", "Database engineering", [
                "Transaction isolation", "Migration strategy",
                "Connection pooling",
            ]),
            ("observability", "Observability", [
                "Structured logging", "Metrics and alerting basics",
                "Distributed tracing intro",
            ]),
            ("testing_backend", "Backend testing", [
                "pytest fixtures and mocking", "Testcontainers for DB tests",
                "Load testing basics",
            ]),
        ],
    },
    "Frontend Engineer": {
        "languages": {"TypeScript": 0.55, "JavaScript": 0.45, "CSS": 0.30},
        "frameworks": {"React": 0.55, "Next.js": 0.40, "Tailwind CSS": 0.30},
        "practices": {"test_signal": 0.35, "has_cicd": True, "commit_quality": 0.30},
        "topics_pool": [
            ("react_advanced", "Advanced React patterns", [
                "Custom hooks", "Context vs state libraries",
                "Performance (memo, lazy, Suspense)",
            ]),
            ("typescript_fe", "TypeScript for UI", [
                "Generics in components", "Discriminated unions for UI state",
                "Strict mode migration",
            ]),
            ("a11y", "Accessibility & UX", [
                "ARIA patterns", "Keyboard navigation",
                "Screen reader testing",
            ]),
            ("css_modern", "Modern CSS & layout", [
                "Flexbox/Grid systems", "Responsive design tokens",
                "Animation performance",
            ]),
            ("fe_testing", "Frontend testing", [
                "Vitest/Jest component tests", "MSW for API mocking",
                "Visual regression intro",
            ]),
        ],
    },
    "DevOps / Platform Engineer": {
        "languages": {"Python": 0.30, "Shell": 0.35, "Go": 0.25},
        "frameworks": {},
        "practices": {"test_signal": 0.3, "has_cicd": True, "commit_quality": 0.40},
        "topics_pool": [
            ("cicd_deep", "CI/CD pipelines", [
                "Multi-stage GitHub Actions", "Matrix builds",
                "Secrets management",
            ]),
            ("containers", "Containers & orchestration", [
                "Dockerfile best practices", "Docker Compose for local dev",
                "Kubernetes fundamentals",
            ]),
            ("iac", "Infrastructure as Code", [
                "Terraform modules", "State management",
                "Environment promotion",
            ]),
            ("monitoring", "Monitoring & SRE", [
                "Prometheus/Grafana basics", "SLIs and SLOs",
                "Incident response runbooks",
            ]),
            ("security_ops", "DevSecOps", [
                "Dependency scanning", "SAST in CI",
                "Least-privilege IAM",
            ]),
        ],
    },
    "ML / AI Engineer": {
        "languages": {"Python": 0.60},
        "frameworks": {"PyTorch": 0.35, "LangChain": 0.30, "Pydantic": 0.40},
        "practices": {"test_signal": 0.35, "has_cicd": True, "commit_quality": 0.30},
        "topics_pool": [
            ("ml_pipeline", "ML pipelines", [
                "Data versioning", "Experiment tracking",
                "Reproducible training scripts",
            ]),
            ("model_eval", "Model evaluation", [
                "Metrics selection", "Cross-validation",
                "Bias and error analysis",
            ]),
            ("llm_apps", "LLM application engineering", [
                "Prompt engineering patterns", "RAG architecture",
                "Evaluation harnesses for LLM outputs",
            ]),
            ("deployment_ml", "ML deployment", [
                "Model serving (FastAPI)", "Batch vs realtime inference",
                "Monitoring model drift",
            ]),
            ("feature_eng", "Feature engineering", [
                "Feature stores intro", "Pipeline orchestration",
                "Data quality checks",
            ]),
        ],
    },
}

# Aliases → canonical role keys
_ROLE_ALIASES: dict[str, str] = {
    "Full-Stack": "Full Stack Engineer",
    "Backend": "Backend Engineer",
    "Frontend": "Frontend Engineer",
    "DevOps": "DevOps / Platform Engineer",
    "ML": "ML / AI Engineer",
    "SDE Intern": "Backend Engineer",
    "Data Engineer": "Backend Engineer",
    "Mobile Engineer": "Frontend Engineer",
    "Security Engineer": "Backend Engineer",
}


def normalize_role(target_role: str) -> str:
    if target_role in ROLE_REQUIREMENTS:
        return target_role
    if target_role in _ROLE_ALIASES:
        return _ROLE_ALIASES[target_role]
    lower = target_role.lower()
    for key in ROLE_REQUIREMENTS:
        if key.lower() in lower or lower in key.lower():
            return key
    return "Full Stack Engineer"


def _has_framework(frameworks: dict[str, float], names: list[str]) -> bool:
    fw_lower = {k.lower(): v for k, v in frameworks.items()}
    for name in names:
        for fw, score in fw_lower.items():
            if name.lower() in fw and score >= 0.5:
                return True
    return False


def _role_skill_objectives(
    report: dict,
    role: str,
) -> list[dict]:
    """Learning objectives derived from role reqs minus current profile."""
    reqs = ROLE_REQUIREMENTS.get(role, ROLE_REQUIREMENTS["Full Stack Engineer"])
    skills = report.get("skills", {})
    frameworks = report.get("frameworks", {})
    objectives: list[dict] = []

    for lang, target in reqs.get("languages", {}).items():
        current = skills.get(lang, 0.0)
        if current < target and current < MASTERED_THRESHOLD:
            objectives.append({
                "type": "language",
                "name": lang,
                "current": current,
                "target": target,
                "priority": target - current,
            })

    for fw, target in reqs.get("frameworks", {}).items():
        current = frameworks.get(fw, 0.0)
        if current < target and current < MASTERED_THRESHOLD:
            # Also check partial matches (e.g. Express via package.json)
            if not _has_framework(frameworks, [fw]):
                objectives.append({
                    "type": "framework",
                    "name": fw,
                    "current": current,
                    "target": target,
                    "priority": target - current,
                })

    objectives.sort(key=lambda x: x["priority"], reverse=True)
    return objectives


def _practice_week(gap: dict, repo: dict | None, week_num: int) -> dict:
    """Build a practice-focused week from a gap + priority repo."""
    repo_name = (repo or {}).get("name", "your top repo")
    lang = (repo or {}).get("language", "project")

    if gap.get("id") == "practice_testing" or "test" in gap.get("title", "").lower():
        return {
            "week": week_num,
            "focus": f"Automated testing on {repo_name}",
            "topics": [
                f"Test structure for {lang} projects",
                "Unit tests for core business logic",
                "CI job running tests on every push",
            ],
            "project_idea": (
                f"Add a test suite to `{repo_name}` covering at least 3 core modules; "
                f"gate merges on passing tests."
            ),
            "reason": (
                f"Gap analysis flagged weak testing ({gap.get('detail', '')}). "
                f"`{repo_name}` is your highest-ROI repo to fix this."
            ),
        }

    if gap.get("id") == "practice_cicd" or "ci/cd" in gap.get("title", "").lower():
        return {
            "week": week_num,
            "focus": f"CI/CD pipeline for {repo_name}",
            "topics": [
                "GitHub Actions workflow design",
                "Lint + test + build stages",
                "Branch protection rules",
            ],
            "project_idea": (
                f"Create `.github/workflows/ci.yml` in `{repo_name}` running lint, "
                f"tests, and build on PR and main."
            ),
            "reason": (
                f"No CI/CD detected across top repos. `{repo_name}` gets automated "
                f"quality gates first."
            ),
        }

    if gap.get("id") == "practice_commits":
        return {
            "week": week_num,
            "focus": "Commit discipline & code review readiness",
            "topics": [
                "Conventional Commits specification",
                "Writing PR descriptions that explain why",
                "Squash vs merge strategies",
            ],
            "project_idea": (
                f"Rewrite the last 10 commits on `{repo_name}` using Conventional Commits; "
                f"open a PR with a structured description template."
            ),
            "reason": gap.get("detail", "Low commit hygiene hurts portfolio signal."),
        }

    if gap.get("id") == "practice_complexity":
        return {
            "week": week_num,
            "focus": f"Refactoring high-complexity code in {repo_name}",
            "topics": [
                "Cyclomatic complexity reduction",
                "Extract-method refactoring",
                "Single-responsibility modules",
            ],
            "project_idea": (
                f"Identify the 2 highest-CC functions in `{repo_name}` Python code; "
                f"refactor into smaller units with tests."
            ),
            "reason": gap.get("detail", "High complexity blocks maintainability."),
        }

    # Generic repo gap
    return {
        "week": week_num,
        "focus": f"Harden {repo_name}",
        "topics": gap.get("action", "Improve project quality").split("; ")[:3]
        or ["Project documentation", "Basic tests", "CI setup"],
        "project_idea": (
            f"Address '{gap.get('title')}' on `{repo_name}` — "
            f"{gap.get('action', 'improve engineering practices')}."
        ),
        "reason": gap.get("detail", f"Priority repo `{repo_name}` needs attention."),
    }


def _skill_week(
    objective: dict,
    topic_block: tuple,
    repo: dict | None,
    week_num: int,
    stack_label: str,
) -> dict:
    """Build a role-skill week from a learning objective."""
    _key, focus_title, topics = topic_block
    repo_name = (repo or {}).get("name", "your main project")
    obj_name = objective.get("name", topic_block[1])

    return {
        "week": week_num,
        "focus": focus_title,
        "topics": topics[:4],
        "project_idea": (
            f"Extend `{repo_name}` with {focus_title.lower()} using {obj_name} — "
            f"build on your existing {stack_label} stack."
        ),
        "reason": (
            f"Role requires {obj_name} (current {objective.get('current', 0):.0%}, "
            f"target {objective.get('target', 0):.0%}). This week closes that gap "
            f"using a repo you already maintain."
        ),
    }


def _capstone_week(
    role: str,
    report: dict,
    week_num: int,
) -> dict:
    stack = report["primary_stack"]["label"]
    top_repo = (
        report["priority_repos"][0]["name"]
        if report["priority_repos"]
        else (report["repo_highlights"][0]["name"] if report.get("repo_highlights") else "capstone")
    )
    return {
        "week": week_num,
        "focus": f"{role} capstone & portfolio polish",
        "topics": [
            "End-to-end feature delivery",
            "Production README with architecture diagram",
            "Demo video or live deployment link",
            "Self-review against role requirements",
        ],
        "project_idea": (
            f"Ship a portfolio-ready feature on `{top_repo}` demonstrating {role} skills: "
            f"tests, CI/CD, docs, and deployed demo."
        ),
        "reason": (
            f"Consolidates your {stack} strengths into a single showcase piece "
            f"reviewers can evaluate in under 5 minutes."
        ),
    }


def build_roadmap_plan(analysis_report: dict, target_role: str) -> dict:
    """
    Deterministic 6-week roadmap from analysis_report.
    Always returns exactly 6 weeks with repo-linked project ideas.
    """
    role = normalize_role(target_role)
    gaps = list(analysis_report.get("gaps", []))
    priority_repos = analysis_report.get("priority_repos", [])
    objectives = _role_skill_objectives(analysis_report, role)
    reqs = ROLE_REQUIREMENTS.get(role, ROLE_REQUIREMENTS["Full Stack Engineer"])
    topics_pool = list(reqs.get("topics_pool", []))

    # Filter topic pool — skip topics for skills already mastered
    skills = analysis_report.get("skills", {})
    frameworks = analysis_report.get("frameworks", {})

    def _topic_relevant(topic_key: str, topics: list[str]) -> bool:
        """Skip JS basics if TS/React already strong."""
        if skills.get("TypeScript", 0) >= MASTERED_THRESHOLD:
            if topic_key in ("react_basics",) or any("javascript basics" in t.lower() for t in topics):
                return False
        if frameworks.get("React", 0) >= MASTERED_THRESHOLD:
            if "react basics" in " ".join(topics).lower():
                return False
        return True

    filtered_topics = [
        t for t in topics_pool if _topic_relevant(t[0], t[2])
    ]

    weeks: list[dict] = []
    used_gaps: set[str] = set()
    repo_iter = iter(priority_repos)
    primary_repo = priority_repos[0] if priority_repos else None

    def _next_repo() -> dict | None:
        nonlocal primary_repo
        try:
            return next(repo_iter)
        except StopIteration:
            return primary_repo

    # Phase 1: Practice gaps (weeks 1–2)
    practice_gaps = [g for g in gaps if g.get("category") in ("practice", "repo")][:2]
    for gap in practice_gaps:
        if len(weeks) >= 2:
            break
        repo = _next_repo() or primary_repo
        weeks.append(_practice_week(gap, repo, len(weeks) + 1))
        used_gaps.add(gap.get("id", ""))

    while len(weeks) < 2 and gaps:
        for gap in gaps:
            if gap.get("id") in used_gaps:
                continue
            weeks.append(_practice_week(gap, _next_repo() or primary_repo, len(weeks) + 1))
            used_gaps.add(gap.get("id", ""))
            if len(weeks) >= 2:
                break
        else:
            break

    # Phase 2: Role skill gaps (weeks 3–4)
    obj_iter = iter(objectives)
    topic_iter = iter(filtered_topics if filtered_topics else topics_pool)

    while len(weeks) < 4:
        obj = next(obj_iter, None)
        topic = next(topic_iter, None)
        if obj and topic:
            weeks.append(_skill_week(
                obj, topic, _next_repo() or primary_repo,
                len(weeks) + 1, analysis_report["primary_stack"]["label"],
            ))
        elif topic:
            weeks.append({
                "week": len(weeks) + 1,
                "focus": topic[1],
                "topics": topic[2][:4],
                "project_idea": (
                    f"Apply {topic[1]} to `{primary_repo['name'] if primary_repo else 'your main repo'}`."
                ),
                "reason": f"Role-aligned skill for {role} not yet covered in your portfolio.",
            })
        else:
            break

    # Phase 3: Integration (week 5)
    if len(weeks) < 5:
        integration_topic = next(topic_iter, None) or (
            "fullstack_integration", "Full-stack integration", [
                "Wire frontend to backend API",
                "Shared validation and error handling",
                "Deploy both layers",
            ]
        )
        weeks.append(_skill_week(
            objectives[0] if objectives else {"name": "integration", "current": 0, "target": 0.5},
            integration_topic,
            primary_repo,
            5,
            analysis_report["primary_stack"]["label"],
        ))

    # Phase 4: Capstone (week 6)
    weeks.append(_capstone_week(role, analysis_report, 6))

    # Pad if somehow short
    while len(weeks) < 6:
        weeks.append(_capstone_week(role, analysis_report, len(weeks) + 1))

    weeks = weeks[:6]
    for i, w in enumerate(weeks, start=1):
        w["week"] = i

    return {
        "target_role": target_role,
        "normalized_role": role,
        "generated_by": "roadmap_engine",
        "maturity_at_generation": analysis_report.get("maturity_score"),
        "primary_stack": analysis_report.get("primary_stack", {}).get("label"),
        "weeks": weeks,
    }


async def polish_roadmap_copy(plan: dict, analysis_report: dict, llm) -> dict:
    """
    Optional LLM pass — rewrites reason/project_idea only; week structure locked.
    """
    from services.llm_service import GroqRateLimitError

    weeks_json = json.dumps(plan["weeks"], indent=2)
    repos = ", ".join(
        r.get("name", "?") for r in analysis_report.get("repo_highlights", [])[:5]
    )
    prompt = (
        f"You polish roadmap copy for a {plan['target_role']} candidate.\n"
        f"Their repos: {repos}\n"
        f"Stack: {analysis_report.get('primary_stack', {}).get('label')}\n\n"
        f"Return JSON: {{\"weeks\": [ ... 6 week objects ... ]}}\n"
        f"Improve ONLY 'reason' and 'project_idea' in each week. "
        f"Keep 'week', 'focus', and 'topics' EXACTLY unchanged.\n\n"
        f"{weeks_json}"
    )
    try:
        polished = await llm.structured_call(
            prompt, max_tokens=2500, max_retries=2, try_fallback=True
        )
        weeks_list = polished.get("weeks") if isinstance(polished, dict) else polished
        if isinstance(weeks_list, list) and len(weeks_list) == 6:
            for i, week in enumerate(weeks_list):
                plan["weeks"][i]["reason"] = week.get("reason", plan["weeks"][i]["reason"])
                plan["weeks"][i]["project_idea"] = week.get(
                    "project_idea", plan["weeks"][i]["project_idea"]
                )
            plan["polished_by"] = "llm"
    except GroqRateLimitError:
        logger.info("Roadmap polish skipped — Groq rate limited")
    except Exception as exc:
        logger.warning("Roadmap polish failed: %s", exc)

    return plan
