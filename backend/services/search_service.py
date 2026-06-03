"""
Search Service — Tavily web-search wrapper.
Runs the synchronous Tavily client in a thread pool to stay non-blocking.
"""

import asyncio
import logging

from tavily import TavilyClient

from core.config import settings

logger = logging.getLogger(__name__)

_MIN_SCORE = 0.3


class SearchService:
    def __init__(self) -> None:
        self.client = TavilyClient(api_key=settings.TAVILY_API_KEY)

    # ------------------------------------------------------------------
    # Core search
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        max_results: int = 5,
        search_depth: str = "basic",
    ) -> list[dict]:
        """
        Execute a Tavily search and return filtered results.

        Each item: {"title": str, "url": str, "content": str, "score": float}
        Results with score < 0.3 are discarded.
        """

        def _sync_search():
            response = self.client.search(
                query=query,
                max_results=max_results,
                search_depth=search_depth,
            )
            return response.get("results", [])

        try:
            raw_results: list[dict] = await asyncio.to_thread(_sync_search)
        except Exception as exc:
            logger.error("Tavily search failed for query=%r: %s", query, exc)
            return []

        filtered = []
        for item in raw_results:
            score = float(item.get("score", 0.0))
            if score < _MIN_SCORE:
                continue
            filtered.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "content": item.get("content", ""),
                    "score": score,
                }
            )

        return filtered

    # ------------------------------------------------------------------
    # Resource-oriented search
    # ------------------------------------------------------------------

    async def search_resources(
        self,
        topic: str,
        difficulty: str = "intermediate",
    ) -> list[dict]:
        """
        Search for learning resources on *topic* at *difficulty* level.
        Augments each result with "difficulty" and "topic" metadata.
        """
        query = f"best {difficulty} tutorial for {topic} programming 2024"
        results = await self.search(query, search_depth="basic")

        # Attach metadata so callers can store directly in the vector store
        for item in results:
            item["difficulty"] = difficulty
            item["topic"] = topic

        return results


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

search_service = SearchService()
