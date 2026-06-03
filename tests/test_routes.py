"""
DevBrain AI — Route Integration Tests (13 tests)

Uses the async_client fixture from conftest.py (httpx + ASGITransport).
All external services (LLM, GitHub, vector store, DB queries) are mocked
so no real network calls or heavy dependencies are needed.
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


# ===========================================================================
# 1. Health check
# ===========================================================================


class TestHealth:
    @pytest.mark.asyncio
    async def test_health_check(self, async_client: AsyncClient):
        response = await async_client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body.get("status") == "ok"


# ===========================================================================
# 2-4. Auth routes
# ===========================================================================


class TestAuthRoutes:
    @pytest.mark.asyncio
    async def test_auth_login_returns_url(self, async_client: AsyncClient):
        """GET /auth/login should redirect or return a GitHub OAuth URL."""
        response = await async_client.get("/auth/login", follow_redirects=False)
        # Accepts 200 with body or 302 redirect — both are valid implementations
        if response.status_code == 200:
            assert "auth_url" in response.json()
        else:
            assert response.status_code in (301, 302, 307, 308)
            assert "github.com" in response.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_auth_me_requires_auth(self, async_client: AsyncClient):
        """GET /auth/me without a token must return 401."""
        response = await async_client.get("/auth/me")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_auth_me_with_valid_token(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        mock_user,
    ):
        """GET /auth/me with a valid JWT should return the current user's data."""
        response = await async_client.get("/auth/me", headers=auth_headers)
        assert response.status_code == 200
        body = response.json()
        # At minimum the response should contain the user's username
        assert body.get("username") == mock_user.github_username or "id" in body


# ===========================================================================
# 5-6. GitHub routes
# ===========================================================================


class TestGitHubRoutes:
    @pytest.mark.asyncio
    async def test_github_analyze_requires_auth(self, async_client: AsyncClient):
        response = await async_client.post("/github/analyze")
        assert response.status_code == 401

    @pytest.mark.asyncio
    @patch("agents.github_analyzer.llm")
    @patch("api.routes.github.cache")
    @patch("agents.github_analyzer.cache")
    @patch("agents.github_analyzer.github_service")
    async def test_github_analyze_success(
        self,
        mock_github,
        mock_agent_cache,
        mock_route_cache,
        mock_llm,
        async_client: AsyncClient,
        auth_headers: dict,
    ):
        mock_route_cache.increment = AsyncMock(return_value=1)
        mock_agent_cache.get_skill_profile = AsyncMock(return_value=None)
        mock_agent_cache.set_skill_profile = AsyncMock(return_value=True)
        mock_agent_cache.delete_skill_profile = AsyncMock(return_value=True)
        mock_agent_cache.delete_progress_dashboard = AsyncMock(return_value=True)
        mock_github.analyze_skill_profile = AsyncMock(
            return_value={
                "skills": {"Python": 0.80, "Shell": 0.25},
                "repo_count": 1,
            }
        )
        mock_llm.call = AsyncMock(return_value="mock narrative summary")

        response = await async_client.post(
            "/github/analyze",
            json={},
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert "skills" in body


# ===========================================================================
# 7-9. Code review routes
# ===========================================================================

SAMPLE_REVIEW_RESPONSE = {
    "review": {
        "summary": "Looks good overall.",
        "issues": [],
        "suggestions": ["Add type hints"],
        "score": 0.88,
    },
    "reflection_loops": 1,
}


MOCK_REVIEW_STATE = {
    "structured_output": {
        "score": 88,
        "annotations": [],
        "complexity": {"time": "O(N)", "space": "O(1)"},
        "edge_cases": [],
        "improvements": [],
        "best_practices": [],
        "summary": "Looks good overall.",
    },
    "iteration_count": 2,
    "reflection_score": 0.88,
}


class TestReviewRoutes:
    @pytest.mark.asyncio
    async def test_review_submit_requires_auth(self, async_client: AsyncClient):
        response = await async_client.post(
            "/review/submit",
            json={"code": "def foo(): pass", "language": "python"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    @patch("api.routes.review.langgraph_app")
    async def test_review_submit_success(
        self,
        mock_graph,
        async_client: AsyncClient,
        auth_headers: dict,
    ):
        mock_graph.ainvoke = AsyncMock(return_value=MOCK_REVIEW_STATE)
        response = await async_client.post(
            "/review/submit",
            json={"code": "def foo(): pass", "language": "python"},
            headers=auth_headers,
        )
        assert response.status_code == 201
        assert "review" in response.json()

    @pytest.mark.asyncio
    @patch("api.routes.review.langgraph_app")
    async def test_review_has_reflection_count(
        self,
        mock_graph,
        async_client: AsyncClient,
        auth_headers: dict,
    ):
        mock_graph.ainvoke = AsyncMock(return_value=MOCK_REVIEW_STATE)
        response = await async_client.post(
            "/review/submit",
            json={"code": "def bar(x): return x * 2", "language": "python"},
            headers=auth_headers,
        )
        assert response.status_code == 201
        body = response.json()
        assert isinstance(body.get("reflection_loops"), int)
        assert body.get("reflection_loops") == 1


# ===========================================================================
# 10-11. Resources routes
# ===========================================================================


class TestResourceRoutes:
    @pytest.mark.asyncio
    async def test_resources_search_requires_auth(self, async_client: AsyncClient):
        response = await async_client.get("/resources/search?topic=python")
        assert response.status_code == 401

    @pytest.mark.asyncio
    @patch("agents.resource_agent.llm")
    @patch("api.routes.resources.vector_store")
    async def test_resources_search_returns_list(
        self,
        mock_vs,
        mock_llm,
        async_client: AsyncClient,
        auth_headers: dict,
    ):
        mock_llm.call = AsyncMock(return_value="Python")
        mock_vs.search_resources = AsyncMock(
            return_value=[
                {
                    "title": "Real Python — Data Structures",
                    "url": "https://realpython.com/data-structures",
                    "snippet": "In-depth tutorial on Python data structures.",
                    "distance": 0.1,
                    "source": "chromadb",
                }
            ]
        )
        response = await async_client.get(
            "/resources/search?topic=python",
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert "resources" in body
        assert isinstance(body["resources"], list)


# ===========================================================================
# 12-13. Progress routes
# ===========================================================================

MOCK_DASHBOARD = {
    "streak": 7,
    "total_reviews": 14,
    "total_challenges": 22,
    "skill_deltas": {"Python": +0.12, "SQL": +0.08},
    "exam_readiness": 0.68,
    "recent_activity": [],
}


class TestProgressRoutes:
    @pytest.mark.asyncio
    async def test_progress_dashboard_requires_auth(self, async_client: AsyncClient):
        response = await async_client.get("/progress/dashboard")
        assert response.status_code == 401

    @pytest.mark.asyncio
    @patch("api.routes.progress.progress_agent_node")
    async def test_progress_dashboard_returns_streak(
        self,
        mock_progress_fn,
        async_client: AsyncClient,
        auth_headers: dict,
        mock_user,
    ):
        mock_progress_fn.return_value = {
            "structured_output": {
                "user": {
                    "id": str(mock_user.id),
                    "github_id": mock_user.github_id,
                    "username": mock_user.github_username,
                    "email": None,
                    "avatar_url": mock_user.avatar_url,
                    "name": mock_user.display_name,
                    "created_at": "2026-06-03T18:15:13",
                    "updated_at": "2026-06-03T18:15:13",
                },
                "streak": {
                    "current_streak": 7,
                    "longest_streak": 10,
                    "last_activity_date": "2026-06-03",
                },
                "skill_profile": {
                    "user_id": str(mock_user.id),
                    "github_username": mock_user.github_username,
                    "skills": {"Python": 0.80, "SQL": 0.60},
                    "summary": "Looks good",
                    "repo_count": 5,
                    "analyzed_at": "2026-06-03T18:15:13",
                },
                "skill_deltas": [
                    {
                        "skill": "Python",
                        "delta_7d": 0.12,
                        "delta_30d": 0.25,
                        "current_score": 0.80,
                    }
                ],
                "total_challenges_solved": 5,
                "total_reviews_submitted": 3,
                "total_interview_sessions": 2,
                "exam_readiness_score": 0.75,
                "exam_readiness": {"Python": 75},
                "weekly_digest": "Great progress this week!",
                "daily_activity": [
                    {
                        "date": "2026-06-03",
                        "challenges_solved": 1,
                        "reviews_submitted": 1,
                        "interview_sessions": 0,
                        "total_activity": 2,
                    }
                ],
                "trend_data": [{"date": "2026-06-03", "score": 75.0}],
                "weekly_challenge_goal": 5,
                "weekly_challenges_done": 2,
                "roadmap_tracker": {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "target_role": "Backend Engineer",
                    "total_weeks": 6,
                    "completed_weeks": 2,
                    "percent_completed": 0.33,
                },
            }
        }
        response = await async_client.get(
            "/progress/dashboard",
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert "streak" in body
        assert isinstance(body["streak"], dict)
        assert body["streak"]["current_streak"] == 7
