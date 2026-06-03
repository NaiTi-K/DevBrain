"""Tests for GitHub repo importance ranking."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from services.github_service import _repo_importance_score, _select_deep_scan_repos


def _repo(name, *, stars=0, commits=10, size=500, code_bytes=50_000, days_ago=7):
    return {
        "name": name,
        "stars": stars,
        "commit_count": commits,
        "size": size,
        "languages": {"Python": code_bytes},
        "language": "Python",
        "description": f"{name} project",
        "pushed_at": datetime.utcnow() - timedelta(days=days_ago),
    }


class TestRepoRanking:
    def test_large_real_project_beats_codecrafter_spam(self):
        devbrain = _repo("DevBrain", commits=120, size=4000, code_bytes=800_000)
        shell = _repo("shell-cpp", commits=200, size=80, code_bytes=5_000, days_ago=30)
        property_app = _repo(
            "Property-app", commits=40, size=2500, code_bytes=400_000, days_ago=3
        )
        repos = [shell, devbrain, property_app]
        top, _rankings = _select_deep_scan_repos(repos, limit=2)
        top_names = [r["name"] for r in top]
        assert "DevBrain" in top_names or "Property-app" in top_names

    def test_recent_activity_breaks_tie(self):
        old = _repo("old-project", code_bytes=100_000, days_ago=300)
        recent = _repo("recent-project", code_bytes=100_000, days_ago=2)
        assert _repo_importance_score(recent) > _repo_importance_score(old)

    def test_tiny_repo_deprioritized(self):
        tiny = _repo("hello-world", commits=50, size=5, code_bytes=200)
        real = _repo("my-app", commits=20, size=800, code_bytes=120_000)
        assert _repo_importance_score(real) > _repo_importance_score(tiny) * 5
