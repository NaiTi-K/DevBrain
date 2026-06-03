"""
DevBrain AI — Test Configuration
Async SQLite in-memory engine, fixtures, and FastAPI dependency overrides.
"""

import asyncio
import uuid
from datetime import datetime, timedelta
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(element, compiler, **kw):
    return "JSON"


# ---------------------------------------------------------------------------
# Patch settings BEFORE importing any app code so modules pick up test values
# ---------------------------------------------------------------------------
TEST_DB_URL = "sqlite+aiosqlite://"  # in-memory, isolated per test run

_settings_patch = patch.dict(
    "os.environ",
    {
        "DATABASE_URL": TEST_DB_URL,
        "REDIS_URL": "redis://localhost:6379/15",
        "XAI_API_KEY": "test-xai-key",
        "GITHUB_CLIENT_ID": "test-gh-client",
        "GITHUB_CLIENT_SECRET": "test-gh-secret",
        "GITHUB_REDIRECT_URI": "http://localhost:8000/auth/callback",
        "JWT_SECRET_KEY": "super-secret-test-key-32-chars!!",
        "JWT_ALGORITHM": "HS256",
        "JWT_EXPIRE_MINUTES": "60",
        "CHROMA_PERSIST_DIR": "/tmp/test_chroma",
        "TAVILY_API_KEY": "test-tavily-key",
        "ENVIRONMENT": "test",
    },
)
_settings_patch.start()

# Now safe to import app modules
from core.security import create_access_token  # noqa: E402
from models.database import Base  # noqa: E402
from models.user import User  # noqa: E402
from models.skill_profile import SkillProfile  # noqa: E402
from main import app  # noqa: E402
from core.dependencies import get_db  # noqa: E402

# ---------------------------------------------------------------------------
# Async test engine — one engine per session, schema created once
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def event_loop():
    """Use a single event loop for the entire test session."""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def test_engine():
    """Create SQLite in-memory engine and all tables once per session."""
    from models.database import engine as db_engine

    engine = db_engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine


@pytest.fixture(scope="session")
def test_session_factory(test_engine):
    """Session factory bound to the test engine."""
    return async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )


# ---------------------------------------------------------------------------
# Per-test DB session with automatic rollback for isolation
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session(test_session_factory) -> AsyncGenerator[AsyncSession, None]:
    """
    Yield an async session that is rolled back after every test.
    Deletes all rows from all tables before each test to guarantee absolute isolation.
    """
    async with test_session_factory() as session:
        # Delete all existing data from all tables to ensure clean state
        for table in reversed(Base.metadata.sorted_tables):
            await session.execute(table.delete())
        await session.commit()

    async with test_session_factory() as session:
        async with session.begin():
            yield session
            await session.rollback()


# ---------------------------------------------------------------------------
# Domain fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def mock_user(db_session: AsyncSession) -> User:
    """Persist a test User and return it."""
    user = User(
        id=uuid.uuid4(),
        github_id=12345,
        github_username="testdev",
        avatar_url="https://avatars.githubusercontent.com/u/12345",
        created_at=datetime.utcnow(),
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def mock_skill_profile(db_session: AsyncSession, mock_user: User) -> SkillProfile:
    """Persist a SkillProfile for mock_user and return it."""
    profile = SkillProfile(
        id=uuid.uuid4(),
        user_id=mock_user.id,
        skills={
            "Python": 0.75,
            "JavaScript": 0.60,
            "TypeScript": 0.55,
            "SQL": 0.40,
            "Docker": 0.30,
            "Rust": 0.10,
        },
        repo_count=12,
        analyzed_at=datetime.utcnow(),
    )
    db_session.add(profile)
    await db_session.flush()
    return profile


@pytest.fixture
def auth_headers(mock_user: User) -> dict[str, str]:
    """Return Authorization headers with a valid JWT for mock_user."""
    token = create_access_token(
        data={"sub": str(mock_user.github_id), "username": mock_user.github_username},
        expires_delta=timedelta(minutes=60),
    )
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# FastAPI async test client with DB override
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def async_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    AsyncClient wrapping the FastAPI app.
    Overrides get_db to inject the rollback-safe test session.
    """

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Shared mock helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_llm():
    """Return a MagicMock standing in for services.llm_service.llm."""
    mock = MagicMock()
    mock.call = AsyncMock(return_value="mocked LLM response")
    mock.structured_call = AsyncMock(return_value={})
    mock.stream = AsyncMock(return_value="streamed content")
    return mock


@pytest.fixture
def mock_cache():
    """Return a MagicMock standing in for services.cache_service.cache."""
    mock = MagicMock()
    mock.get_skill_profile = AsyncMock(return_value=None)
    mock.set_skill_profile = AsyncMock(return_value=True)
    mock.get = AsyncMock(return_value=None)
    mock.set = AsyncMock(return_value=True)
    mock.delete = AsyncMock(return_value=True)
    return mock


@pytest.fixture
def mock_github_service():
    """Return a MagicMock for services.github_service."""
    mock = MagicMock()
    mock.get_user_repos = AsyncMock(
        return_value=[
            {"name": "cool-api", "language": "Python", "stargazers_count": 12},
            {"name": "web-app", "language": "JavaScript", "stargazers_count": 5},
        ]
    )
    mock.analyze_skills = AsyncMock(
        return_value={
            "Python": 0.75,
            "JavaScript": 0.60,
            "TypeScript": 0.50,
        }
    )
    return mock


@pytest.fixture
def mock_vector_store():
    """Return a MagicMock for services.vector_store."""
    mock = MagicMock()
    mock.search = AsyncMock(
        return_value=[
            {
                "title": "Python Data Structures",
                "url": "https://docs.python.org/3/tutorial/datastructures.html",
                "snippet": "Lists, dicts, sets — official Python docs.",
                "score": 0.92,
                "source": "chromadb",
            }
        ]
    )
    mock.add_documents = AsyncMock(return_value=True)
    return mock
