"""
backend/models/database.py
Async SQLAlchemy engine, session factory, and declarative base.
All ORM models must inherit from Base defined here.
"""

from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from core.config import settings

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
engine_kwargs = {
    "echo": False,
}
if "sqlite" in settings.DATABASE_URL:
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    engine_kwargs.update({
        "pool_size": 5,
        "max_overflow": 10,
        "pool_recycle": 1800,
    })

engine = create_async_engine(
    settings.DATABASE_URL,
    **engine_kwargs
)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ---------------------------------------------------------------------------
# Declarative base
# ---------------------------------------------------------------------------
class Base(AsyncAttrs, DeclarativeBase):
    """
    All ORM models inherit from this base.
    AsyncAttrs mixin enables awaitable lazy-loading on relationships
    (``await instance.awaitable_attrs.relationship_name``).
    """
