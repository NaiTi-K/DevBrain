"""
Vector Store Service — ChromaDB-backed semantic search.
Three collections:
  • code_snippets      — past AI code reviews
  • learning_resources — curated / scraped learning resources
  • session_history    — per-user conversational memory
"""

import asyncio
import logging

import chromadb
from chromadb.config import Settings as ChromaSettings
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

logger = logging.getLogger(__name__)


class VectorStoreService:
    def __init__(self) -> None:
        # Disable telemetry — avoids posthog/chroma version mismatch noise on startup
        self._client = chromadb.PersistentClient(
            path="./data/chroma",
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._emb_fn = SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
        _cosine = {"hnsw:space": "cosine"}

        self.code_collection = self._client.get_or_create_collection(
            "code_snippets",
            embedding_function=self._emb_fn,
            metadata=_cosine,
        )
        self.resource_collection = self._client.get_or_create_collection(
            "learning_resources",
            embedding_function=self._emb_fn,
            metadata=_cosine,
        )
        self.session_collection = self._client.get_or_create_collection(
            "session_history",
            embedding_function=self._emb_fn,
            metadata=_cosine,
        )

        logger.info("VectorStoreService initialised (ChromaDB persistent).")

    # ------------------------------------------------------------------
    # Code Review Collection
    # ------------------------------------------------------------------

    async def add_code_review(
        self,
        review_id: str,
        code: str,
        language: str,
        review_summary: str,
        user_id: str,
    ) -> None:
        """Store a code review for future similarity search."""
        document = f"{language} code: {code[:500]}\nReview: {review_summary}"

        def _add():
            self.code_collection.add(
                ids=[review_id],
                documents=[document],
                metadatas=[
                    {
                        "review_id": review_id,
                        "user_id": user_id,
                        "language": language,
                    }
                ],
            )

        await asyncio.to_thread(_add)

    async def search_similar_reviews(
        self,
        code: str,
        language: str,
        n_results: int = 3,
    ) -> list[dict]:
        """
        Return the *n_results* most similar past reviews.
        Each item: {"document": str, "metadata": dict, "distance": float}
        """
        query = f"{language} code: {code[:500]}"

        def _query():
            results = self.code_collection.query(
                query_texts=[query],
                n_results=n_results,
            )
            return self._zip_results(results)

        return await asyncio.to_thread(_query)

    # ------------------------------------------------------------------
    # Learning Resources Collection
    # ------------------------------------------------------------------

    async def add_resource(
        self,
        resource_id: str,
        title: str,
        description: str,
        topic: str,
        difficulty: str,
        url: str,
        source: str,
    ) -> None:
        """Index a learning resource."""
        document = f"{title}: {description}"

        def _add():
            self.resource_collection.add(
                ids=[resource_id],
                documents=[document],
                metadatas=[
                    {
                        "title": title,
                        "topic": topic,
                        "difficulty": difficulty,
                        "url": url,
                        "source": source,
                    }
                ],
            )

        await asyncio.to_thread(_add)

    async def search_resources(
        self,
        query: str,
        topic: str = "",
        n_results: int = 5,
    ) -> list[dict]:
        """
        Semantic search over learning resources.
        Optionally filters by *topic*.
        Each item: {"title": str, "url": str, "topic": str, "difficulty": str, "distance": float}
        """
        where = {"topic": topic} if topic else None
        kwargs: dict = {"query_texts": [query], "n_results": n_results}
        if where:
            kwargs["where"] = where

        def _query():
            results = self.resource_collection.query(**kwargs)
            rows = self._zip_results(results)
            return [
                {
                    "title": r["metadata"].get("title", ""),
                    "url": r["metadata"].get("url", ""),
                    "topic": r["metadata"].get("topic", ""),
                    "difficulty": r["metadata"].get("difficulty", ""),
                    "distance": r["distance"],
                }
                for r in rows
            ]

        return await asyncio.to_thread(_query)

    async def list_resource_topics(self) -> list[str]:
        """Retrieve unique topics indexed in the resource collection."""

        def _get():
            results = self.resource_collection.get(include=["metadatas"])
            metadatas = results.get("metadatas") or []
            topics = set()
            for meta in metadatas:
                if meta and "topic" in meta:
                    topics.add(meta["topic"])
            return list(topics)

        return await asyncio.to_thread(_get)

    # ------------------------------------------------------------------
    # Session Memory Collection
    # ------------------------------------------------------------------

    async def add_session_memory(
        self,
        session_id: str,
        user_id: str,
        content: str,
        session_type: str,
    ) -> None:
        """Persist a session turn for long-term user context."""

        def _add():
            self.session_collection.add(
                ids=[session_id],
                documents=[content],
                metadatas=[
                    {
                        "user_id": user_id,
                        "session_type": session_type,
                    }
                ],
            )

        await asyncio.to_thread(_add)

    async def get_user_context(
        self,
        user_id: str,
        query: str,
        n_results: int = 3,
    ) -> list[str]:
        """
        Retrieve the most relevant session snippets for a user.
        Returns a list of plain document strings.
        """

        def _query():
            results = self.session_collection.query(
                query_texts=[query],
                n_results=n_results,
                where={"user_id": user_id},
            )
            rows = self._zip_results(results)
            return [r["document"] for r in rows]

        return await asyncio.to_thread(_query)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _zip_results(results: dict) -> list[dict]:
        """
        Flatten a ChromaDB query result into a list of
        {"document": str, "metadata": dict, "distance": float}.
        """
        docs = (results.get("documents") or [[]])[0]
        metas = (results.get("metadatas") or [[]])[0]
        distances = (results.get("distances") or [[]])[0]

        output = []
        for doc, meta, dist in zip(docs, metas, distances):
            output.append(
                {
                    "document": doc,
                    "metadata": meta or {},
                    "distance": dist,
                }
            )
        return output


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

vector_store = VectorStoreService()
