"""
LLM Service — wraps Groq API (OpenAI-compatible).
Fails fast on rate limits so user-facing routes don't block for minutes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import AsyncGenerator

import httpx

from core.config import settings

logger = logging.getLogger(__name__)

_DEFAULT_SYSTEM = (
    "You are DevBrain, an expert developer mentor and senior software engineer."
)

_MIN_CALL_INTERVAL = 1.0
_DEFAULT_MAX_RETRIES = 3
# Never block an HTTP request longer than this waiting on Groq 429
_MAX_RETRY_WAIT_SEC = 60.0


class GroqRateLimitError(Exception):
    """Raised when Groq returns 429 and we should not keep the user waiting."""

    def __init__(self, retry_after: float = 60.0, message: str = "Groq rate limit exceeded"):
        self.retry_after = retry_after
        super().__init__(message)


class LLMService:
    def __init__(self) -> None:
        self.api_key = settings.XAI_API_KEY
        self.base_url = "https://api.groq.com/openai/v1/chat/completions"
        self.model = settings.GROK_MODEL
        self.fallback_model = settings.GROQ_FALLBACK_MODEL
        self._lock = asyncio.Lock()
        self._last_call_at = 0.0
        self._cooldown_until = 0.0

    def seconds_until_available(self) -> float:
        return max(0.0, self._cooldown_until - time.monotonic())

    async def _throttle(self) -> None:
        remaining = self.seconds_until_available()
        if remaining > 0:
            if remaining <= _MAX_RETRY_WAIT_SEC:
                await asyncio.sleep(remaining)
            else:
                raise GroqRateLimitError(
                    retry_after=remaining,
                    message=f"Groq cooldown active — retry in {int(remaining)}s",
                )
        async with self._lock:
            elapsed = time.monotonic() - self._last_call_at
            if elapsed < _MIN_CALL_INTERVAL:
                await asyncio.sleep(_MIN_CALL_INTERVAL - elapsed)
            self._last_call_at = time.monotonic()

    @staticmethod
    def _parse_retry_after(response: httpx.Response | None) -> float:
        if response is None:
            return 60.0
        raw = response.headers.get("retry-after")
        if not raw:
            return 60.0
        try:
            return float(raw)
        except ValueError:
            return 60.0

    def _register_rate_limit(self, response: httpx.Response | None) -> float:
        wait = self._parse_retry_after(response)
        self._cooldown_until = max(
            self._cooldown_until,
            time.monotonic() + wait,
        )
        return wait

    async def call(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 4096,
        temperature: float | None = None,
        *,
        model: str | None = None,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        try_fallback: bool = True,
    ) -> str:
        """
        Single-turn chat completion.
        On 429: never sleeps more than _MAX_RETRY_WAIT_SEC; sets a cooldown
        and raises GroqRateLimitError so callers can use deterministic fallback.
        """
        target_model = model or self.model
        system_msg = system or _DEFAULT_SYSTEM
        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": prompt},
        ]

        last_exc: Exception | None = None

        for attempt in range(max_retries):
            await self._throttle()
            try:
                payload: dict = {
                    "model": target_model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                }
                if temperature is not None:
                    payload["temperature"] = temperature

                async with httpx.AsyncClient(timeout=90.0) as client:
                    response = await client.post(
                        self.base_url,
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json=payload,
                    )

                    if response.status_code in (429, 529):
                        wait = self._register_rate_limit(response)
                        last_exc = GroqRateLimitError(retry_after=wait)
                        logger.warning(
                            "Groq %d on model=%s (retry-after=%.0fs, attempt %d/%d)",
                            response.status_code,
                            target_model,
                            wait,
                            attempt + 1,
                            max_retries,
                        )
                        # Only wait if Groq asks for a short retry — never block 60s
                        if wait <= _MAX_RETRY_WAIT_SEC and attempt < max_retries - 1:
                            await asyncio.sleep(wait)
                            continue
                        break

                    response.raise_for_status()
                    data = response.json()
                    return data["choices"][0]["message"]["content"] or ""

            except GroqRateLimitError:
                raise
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (429, 529):
                    wait = self._register_rate_limit(exc.response)
                    last_exc = GroqRateLimitError(retry_after=wait)
                    logger.warning(
                        "Groq HTTP %d on model=%s (retry-after=%.0fs)",
                        exc.response.status_code,
                        target_model,
                        wait,
                    )
                    if wait <= _MAX_RETRY_WAIT_SEC and attempt < max_retries - 1:
                        await asyncio.sleep(wait)
                        continue
                    break
                raise
            except httpx.RequestError as exc:
                last_exc = exc
                if attempt < max_retries - 1:
                    await asyncio.sleep(min(2 ** attempt, 5.0))
                    continue
                break

        # Try cheaper/faster model (separate Groq rate-limit bucket)
        if (
            try_fallback
            and target_model != self.fallback_model
            and isinstance(last_exc, GroqRateLimitError)
        ):
            logger.info(
                "Primary model rate-limited — trying fallback model %s",
                self.fallback_model,
            )
            try:
                return await self.call(
                    prompt,
                    system=system,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    model=self.fallback_model,
                    max_retries=2,
                    try_fallback=False,
                )
            except Exception as exc:
                logger.warning("Fallback model also failed: %s", exc)

        if isinstance(last_exc, GroqRateLimitError):
            raise last_exc
        raise last_exc  # type: ignore[misc]

    async def structured_call(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 4096,
        **call_kwargs,
    ) -> dict:
        json_prompt = (
            prompt
            + "\nIMPORTANT: Respond with ONLY valid JSON. "
            "No markdown, no explanation, just the JSON object."
        )

        raw = await self.call(
            json_prompt, system=system, max_tokens=max_tokens, **call_kwargs
        )
        parsed, error = self._try_parse(raw)
        if parsed is not None:
            return parsed

        logger.warning("First JSON parse failed (%s); retrying with corrective prompt.", error)
        corrective = (
            f"Your previous response could not be parsed as JSON.\n"
            f"Error: {error}\n"
            f"Raw response:\n{raw}\n\n"
            "Please return ONLY the corrected, valid JSON object — no explanation, no markdown."
        )
        raw2 = await self.call(
            corrective, system=system, max_tokens=max_tokens, **call_kwargs
        )
        parsed2, _error2 = self._try_parse(raw2)
        if parsed2 is not None:
            return parsed2

        raise ValueError(
            f"LLM returned invalid JSON after two attempts.\nRaw response:\n{raw2}"
        )

    @staticmethod
    def _try_parse(text: str) -> tuple[dict | None, str]:
        import re

        cleaned = text.strip()
        fenced = re.search(r"```(?:json)?\s*([\s\S]+?)```", cleaned)
        if fenced:
            cleaned = fenced.group(1).strip()
        try:
            return json.loads(cleaned), ""
        except json.JSONDecodeError as exc:
            match = re.search(r"\{[\s\S]+\}", cleaned)
            if match:
                try:
                    return json.loads(match.group()), ""
                except json.JSONDecodeError as exc2:
                    return None, f"Regex fallback failed: {exc2}"
            return None, str(exc)

    async def stream(
        self,
        prompt: str,
        system: str = "",
    ) -> AsyncGenerator[str, None]:
        system_msg = system or _DEFAULT_SYSTEM
        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": prompt},
        ]

        await self._throttle()
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                self.base_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": True,
                },
                timeout=90.0,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            choices = data.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {}).get("content")
                                if delta:
                                    yield delta
                        except json.JSONDecodeError:
                            continue


llm = LLMService()
