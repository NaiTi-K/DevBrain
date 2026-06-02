"""
backend/core/config.py
Central configuration — loaded once at import time from .env / environment variables.
All other modules import `settings` from here.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str  # must start with postgresql+asyncpg://

    # ── Cache / Queue ─────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── Groq LLM (key is GROQ API key despite legacy env name) ───────────────
    XAI_API_KEY: str
    GROK_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_FALLBACK_MODEL: str = "llama-3.1-8b-instant"

    # ── GitHub OAuth ──────────────────────────────────────────────────────────
    GITHUB_CLIENT_ID: str
    GITHUB_CLIENT_SECRET: str
    GITHUB_PAT: str = ""  # optional — needed only for private-repo analysis

    # ── Tavily web search ─────────────────────────────────────────────────────
    TAVILY_API_KEY: str

    # ── JWT auth ──────────────────────────────────────────────────────────────
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440  # 24 hours

    # ── Service URLs ──────────────────────────────────────────────────────────
    FRONTEND_URL: str = "http://localhost:3000"
    BACKEND_URL: str = "http://localhost:8000"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


# Singleton — import this everywhere
settings: Settings = get_settings()
