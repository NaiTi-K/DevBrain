"""
Auth API routes — GitHub OAuth and JWT session handling.
"""

from __future__ import annotations

from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.dependencies import get_current_user, get_db
from core.security import create_access_token
from models.user import User

router = APIRouter(tags=["auth"])

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"


def _oauth_redirect_uri() -> str:
    base = settings.BACKEND_URL.rstrip("/")
    return f"{base}/auth/callback"


class AuthLoginResponse(BaseModel):
    auth_url: str


class UserResponse(BaseModel):
    id: str
    github_id: int
    username: str
    email: str | None = None
    avatar_url: str | None = None
    name: str | None = None
    created_at: str
    updated_at: str

    @classmethod
    def from_user(cls, user: User) -> UserResponse:
        created = user.created_at.isoformat() if user.created_at else ""
        return cls(
            id=str(user.id),
            github_id=user.github_id,
            username=user.github_username,
            email=None,
            avatar_url=user.avatar_url,
            name=user.display_name,
            created_at=created,
            updated_at=created,
        )


@router.get("/login", response_model=AuthLoginResponse)
async def login() -> AuthLoginResponse:
    """Return the GitHub OAuth authorization URL for the frontend."""
    params = {
        "client_id": settings.GITHUB_CLIENT_ID,
        "redirect_uri": _oauth_redirect_uri(),
        "scope": "read:user public_repo",
    }
    return AuthLoginResponse(auth_url=f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}")


@router.get("/callback")
async def oauth_callback(
    code: str | None = Query(None),
    error: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """
    GitHub redirects here with ?code=...
    Exchange code for access token, upsert user, issue JWT,
    redirect to frontend /auth/callback?token=...
    """
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"GitHub OAuth error: {error}",
        )
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing authorization code",
        )

    async with httpx.AsyncClient(timeout=30.0) as client:
        token_response = await client.post(
            GITHUB_TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.GITHUB_CLIENT_ID,
                "client_secret": settings.GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": _oauth_redirect_uri(),
            },
        )
        if token_response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to exchange GitHub authorization code",
            )

        token_data = token_response.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=token_data.get("error_description", "No access token from GitHub"),
            )

        user_response = await client.get(
            GITHUB_USER_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            },
        )
        if user_response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to fetch GitHub user profile",
            )

        gh_user = user_response.json()

    github_id = int(gh_user["id"])
    github_username = gh_user["login"]
    avatar_url = gh_user.get("avatar_url")
    display_name = gh_user.get("name") or github_username

    result = await db.execute(select(User).where(User.github_id == github_id))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            github_id=github_id,
            github_username=github_username,
            display_name=display_name,
            avatar_url=avatar_url,
        )
        db.add(user)
    else:
        user.github_username = github_username
        user.display_name = display_name
        user.avatar_url = avatar_url

    await db.flush()

    jwt_token = create_access_token({"sub": str(github_id)})
    frontend_callback = (
        f"{settings.FRONTEND_URL.rstrip('/')}/auth/callback"
        f"?token={jwt_token}"
    )
    return RedirectResponse(url=frontend_callback, status_code=status.HTTP_302_FOUND)


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)) -> UserResponse:
    """Return the authenticated user."""
    return UserResponse.from_user(current_user)
