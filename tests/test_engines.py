"""Unit tests for profile_engine and roadmap_engine deterministic pipelines."""

import pytest

from services.profile_engine import (
    build_analysis_report,
    compute_maturity_score,
    render_analysis_markdown,
)
from services.roadmap_engine import build_roadmap_plan, normalize_role


SAMPLE_PROFILE = {
    "skills": {"Python": 1.0, "TypeScript": 0.81, "JavaScript": 0.11, "C++": 0.11},
    "frameworks": {"React": 0.85, "Vite": 0.85, "Jest": 0.85, "FastAPI": 0.85},
    "engineering_practices": {
        "has_cicd": True,
        "test_signal": 0.2,
        "commit_quality": 0.12,
        "avg_complexity": 23.8,
        "class_count": 5,
        "function_count": 20,
    },
    "repo_highlights": [
        {
            "name": "Property-app",
            "description": "Real estate app",
            "stars": 2,
            "primary_language": "TypeScript",
            "has_cicd": False,
            "has_tests": False,
            "frameworks": ["React", "Vite", "Tailwind CSS"],
            "sample_commits": ["feat: add listing page"],
        },
        {
            "name": "DevBrain",
            "description": "AI dev platform",
            "stars": 1,
            "primary_language": "Python",
            "has_cicd": True,
            "has_tests": True,
            "frameworks": ["FastAPI", "LangGraph"],
            "sample_commits": ["feat: github analyzer"],
        },
        {
            "name": "shell-cpp",
            "description": "",
            "stars": 0,
            "primary_language": "C++",
            "has_cicd": False,
            "has_tests": False,
            "frameworks": [],
            "sample_commits": ["codecrafters submit [skip ci]"],
        },
    ],
    "sample_commits": ["feat: add listing page", "codecrafters submit [skip ci]"],
    "repo_count": 5,
    "used_github_token": True,
}


class TestProfileEngine:
    def test_build_analysis_report_structure(self):
        report = build_analysis_report(SAMPLE_PROFILE, "testdev")
        assert report["repo_count"] == 5
        assert "Python" in report["primary_stack"]["languages"]
        assert report["maturity_score"] > 0
        assert len(report["gaps"]) >= 2
        assert len(report["priority_repos"]) == 3
        assert report["priority_repos"][0]["name"] in ("Property-app", "shell-cpp")

    def test_gaps_include_practice_and_repo(self):
        report = build_analysis_report(SAMPLE_PROFILE, "testdev")
        gap_ids = {g["id"] for g in report["gaps"]}
        assert "practice_commits" in gap_ids or "practice_testing" in gap_ids
        assert any(g["category"] == "repo" for g in report["gaps"])

    def test_render_markdown_mentions_repos(self):
        report = build_analysis_report(SAMPLE_PROFILE, "testdev")
        md = render_analysis_markdown(report)
        assert "Property-app" in md or "DevBrain" in md
        assert "#### Technical Strengths" in md
        assert "#### Recommended Roadmap Focus" in md

    def test_maturity_score_bounded(self):
        ep = SAMPLE_PROFILE["engineering_practices"]
        score = compute_maturity_score(ep)
        assert 0.0 <= score <= 1.0


class TestRoadmapEngine:
    @pytest.fixture
    def report(self):
        return build_analysis_report(SAMPLE_PROFILE, "testdev")

    def test_normalize_role_aliases(self):
        assert normalize_role("Full-Stack") == "Full Stack Engineer"
        assert normalize_role("Backend") == "Backend Engineer"

    def test_build_roadmap_six_weeks(self, report):
        plan = build_roadmap_plan(report, "Full Stack Engineer")
        assert len(plan["weeks"]) == 6
        assert plan["generated_by"] == "roadmap_engine"
        for i, week in enumerate(plan["weeks"], start=1):
            assert week["week"] == i
            assert week["focus"]
            assert len(week["topics"]) >= 2
            assert week["project_idea"]
            assert week["reason"]

    def test_roadmap_references_user_repos(self, report):
        plan = build_roadmap_plan(report, "Full Stack Engineer")
        combined = " ".join(w["project_idea"] + w["reason"] for w in plan["weeks"])
        assert (
            "Property-app" in combined
            or "shell-cpp" in combined
            or "DevBrain" in combined
        )

    def test_roadmap_skips_js_basics_for_ts_master(self, report):
        """TypeScript at 81% — plan should not start with generic JS basics."""
        plan = build_roadmap_plan(report, "Full Stack Engineer")
        week1 = plan["weeks"][0]["focus"].lower()
        assert "javascript basics" not in week1

    def test_no_generic_pad_weeks(self, report):
        plan = build_roadmap_plan(report, "Backend Engineer")
        assert "Advanced Practice & Review" not in plan["weeks"][0]["focus"]
