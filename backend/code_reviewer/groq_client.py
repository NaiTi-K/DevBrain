"""
groq_client.py
Thin wrapper around the existing LLM service.
Single responsibility: make the API call, return the result.
All prompt building happens in prompts.py.
All analysis happens in pre_analyzer.py.
"""

from typing import AsyncGenerator
from services.llm_service import llm


async def call_groq(system_prompt: str, user_prompt: str) -> str:
    """
    Make a single Groq API call and return the full response as a string.
    Used by the structured review endpoint (POST /code-reviewer/review).

    Args:
        system_prompt: the system message (sets LLM persona)
        user_prompt: the user message (the actual review request)

    Returns:
        The LLM response as a plain string (markdown).
    """
    return await llm.call(
        prompt=user_prompt,
        system=system_prompt,
    )


async def stream_groq(system_prompt: str, user_prompt: str) -> AsyncGenerator[str, None]:
    """
    Make a streaming Groq API call and yield text chunks as they arrive.
    Used by the streaming endpoint (GET /code-reviewer/stream).

    Args:
        system_prompt: the system message
        user_prompt: the user message

    Yields:
        String chunks of the LLM response as they stream in.
    """
    async for chunk in llm.stream(
        prompt=user_prompt,
        system=system_prompt,
    ):
        yield chunk
