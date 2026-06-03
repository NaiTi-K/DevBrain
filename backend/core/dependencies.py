"""
backend/core/dependencies.py
FastAPI dependency functions shared across all route modules.
"""

from typing import AsyncGenerator

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import verify_token
from models.database import async_session

# ---------------------------------------------------------------------------
# OAuth2 scheme — auto_error=False so optional routes don't raise 401
# ---------------------------------------------------------------------------
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/auth/login",
    auto_error=False,
)


# ---------------------------------------------------------------------------
# Database session
# ---------------------------------------------------------------------------
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Yield a single :class:`AsyncSession` per request.
    Commits on clean exit, rolls back on any exception, always closes.
    """
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ---------------------------------------------------------------------------
# Current-user helpers
# ---------------------------------------------------------------------------
async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    """
    Require a valid JWT and return the matching :class:`User` row.
    Raises HTTP 401 on any failure.
    """
    # Import here to avoid circular imports at module load time
    from models.user import User  # noqa: PLC0415

    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if token is None:
        raise credentials_exc

    payload = verify_token(token)
    if payload is None:
        raise credentials_exc

    github_id_str: str | None = payload.get("sub")
    if github_id_str is None:
        raise credentials_exc

    try:
        github_id = int(github_id_str)
    except (ValueError, TypeError):
        raise credentials_exc

    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(User).options(selectinload(User.skill_profiles)).where(User.github_id == github_id)
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exc

    return user


async def get_optional_user(
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    """
    Same as :func:`get_current_user` but returns ``None`` instead of
    raising 401 when no valid token is present.
    """
    if token is None:
        return None

    try:
        return await get_current_user(token=token, db=db)
    except HTTPException:
        return None
