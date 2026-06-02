"""
backend/alembic/env.py
Async Alembic environment — supports `alembic revision --autogenerate`
and `alembic upgrade head` against an asyncpg PostgreSQL database.

Pattern: asyncio.run(run_async_migrations()) for both online and offline modes.
"""

import asyncio
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

# ── Ensure backend/ is on sys.path so imports work ───────────────────────────
# Alembic is invoked from backend/, so this is usually already the case,
# but we add it explicitly for robustness.
_backend_dir = os.path.dirname(os.path.dirname(__file__))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# ── Import settings (must come after sys.path setup) ──────────────────────────
from core.config import settings  # noqa: E402

# ── Import Base and ALL models so metadata is fully populated ─────────────────
# The wildcard import of models ensures every table is registered on Base.metadata
# before autogenerate inspects it.
from models.database import Base  # noqa: E402
import models  # noqa: E402, F401  — side-effect: registers all ORM classes

# ── Alembic Config object ─────────────────────────────────────────────────────
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Provide the declarative metadata to Alembic for autogenerate support
target_metadata = Base.metadata

# Override sqlalchemy.url with the value from our settings
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)


# ── Offline migrations ────────────────────────────────────────────────────────

def run_migrations_offline() -> None:
    """
    Run migrations without a live DB connection.
    Emits SQL to stdout / a file.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# ── Online migrations (async) ────────────────────────────────────────────────

async def run_async_migrations() -> None:
    """
    Create an async engine and run migrations inside a begin/commit block.
    """
    connectable = create_async_engine(
        settings.DATABASE_URL,
        # Echo DDL in migration context for visibility
        echo=False,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)

    await connectable.dispose()


def _do_run_migrations(connection) -> None:
    """Synchronous inner function called via run_sync."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Entry point for online mode — drives the async function via asyncio.run."""
    asyncio.run(run_async_migrations())


# ── Dispatch ─────────────────────────────────────────────────────────────────

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
