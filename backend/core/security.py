"""
backend/core/security.py
JWT creation and verification helpers.
Uses python-jose[cryptography].
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt

from core.config import settings


def create_access_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    """
    Sign and return a JWT.

    Parameters
    ----------
    data:
        Arbitrary claims to embed.  A copy is made so the caller's dict is
        not mutated.
    expires_delta:
        How long the token should live.  Defaults to
        settings.JWT_EXPIRE_MINUTES if not supplied.

    Returns
    -------
    str
        Encoded JWT string.
    """
    payload = data.copy()

    expire = datetime.now(tz=timezone.utc) + (
        expires_delta if expires_delta is not None else timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    )
    payload["exp"] = expire

    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def verify_token(token: str) -> dict[str, Any] | None:
    """
    Decode and validate a JWT.

    Returns the decoded payload dict, or ``None`` on any error
    (expired, bad signature, malformed, etc.).
    """
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError:
        return None
