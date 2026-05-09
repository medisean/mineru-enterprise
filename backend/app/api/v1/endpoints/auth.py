"""
Auth endpoints: local login, SSO redirect/callback, token refresh.
"""
import secrets
import json
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import (
    verify_password, hash_password,
    create_access_token, create_refresh_token, decode_token,
)
from app.core.config import settings
from app.models.models import User, SSOProvider
from app.schemas.schemas import LoginRequest, TokenResponse, RefreshRequest, UserCreate, UserOut, SSOCallbackRequest
from app.services.sso import oidc_provider, wechat_work_oauth, dingtalk_oauth, ldap_service

router = APIRouter(prefix="/auth", tags=["auth"])

# SSO state TTL in seconds (10 minutes)
_SSO_STATE_TTL = 600


def _get_redis():
    """Get a Redis client for SSO state storage."""
    import redis
    return redis.from_url(settings.REDIS_URL)


def _store_sso_state(state: str, provider: str):
    """Store SSO state in Redis with TTL."""
    r = _get_redis()
    r.setex(f"sso_state:{state}", _SSO_STATE_TTL, provider)


def _consume_sso_state(state: str) -> str | None:
    """Consume and validate SSO state from Redis. Returns provider if valid, None otherwise."""
    r = _get_redis()
    key = f"sso_state:{state}"
    provider = r.get(key)
    if provider is None:
        return None
    # Delete after read (one-time use)
    r.delete(key)
    return provider.decode("utf-8") if isinstance(provider, bytes) else provider


def _make_tokens(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ── Local auth ────────────────────────────────────────────────────────────────
@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(User).where(
            (User.email == payload.username) | (User.username == payload.username)
        )
    )
    user = result.scalar_one_or_none()

    # Try LDAP if no local user
    if user is None and settings.LDAP_ENABLED:
        ldap_info = ldap_service.authenticate(payload.username, payload.password)
        if ldap_info:
            user = await _get_or_create_sso_user(db, ldap_info, SSOProvider.LDAP)
            return _make_tokens(user)

    if not user or not user.hashed_password or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    return _make_tokens(user)


@router.post("/register", response_model=UserOut)
async def register(payload: UserCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(
        select(User).where((User.email == payload.email) | (User.username == payload.username))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email or username already taken")

    user = User(
        email=payload.email,
        username=payload.username,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        sso_provider=SSOProvider.LOCAL,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(payload: RefreshRequest, db: AsyncSession = Depends(get_db)):
    data = decode_token(payload.refresh_token)
    if not data or data.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    result = await db.execute(select(User).where(User.id == data["sub"]))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found")
    return _make_tokens(user)


# ── SSO redirect ──────────────────────────────────────────────────────────────
@router.get("/sso/{provider}/authorize")
async def sso_authorize(provider: str):
    state = secrets.token_urlsafe(16)
    _store_sso_state(state, provider)
    redirect_uri = f"{settings.FRONTEND_URL}/api/auth/callback/{provider}"

    if provider == "oidc" and settings.OIDC_ENABLED and oidc_provider:
        url = await oidc_provider.get_authorization_url(redirect_uri, state)
    elif provider == "wechat_work" and settings.WECHAT_WORK_ENABLED and wechat_work_oauth:
        url = wechat_work_oauth.get_authorization_url(redirect_uri, state)
    elif provider == "dingtalk" and settings.DINGTALK_ENABLED and dingtalk_oauth:
        url = dingtalk_oauth.get_authorization_url(redirect_uri, state)
    else:
        raise HTTPException(status_code=400, detail=f"SSO provider '{provider}' not enabled")

    return {"authorization_url": url, "state": state}


@router.post("/sso/callback", response_model=TokenResponse)
async def sso_callback(payload: SSOCallbackRequest, db: AsyncSession = Depends(get_db)):
    # Validate state to prevent CSRF
    stored_provider = _consume_sso_state(payload.state)
    if stored_provider is None:
        raise HTTPException(status_code=400, detail="Invalid or expired SSO state. Please retry the login flow.")
    if stored_provider != payload.provider:
        raise HTTPException(status_code=400, detail="SSO provider mismatch. Possible CSRF attack.")

    redirect_uri = f"{settings.FRONTEND_URL}/api/auth/callback/{payload.provider}"

    if payload.provider == "oidc" and oidc_provider:
        user_info = await oidc_provider.exchange_code(payload.code, redirect_uri)
        sso_provider = SSOProvider.OIDC
    elif payload.provider == "wechat_work" and wechat_work_oauth:
        user_info = await wechat_work_oauth.get_user_info(payload.code)
        sso_provider = SSOProvider.WECHAT_WORK
    elif payload.provider == "dingtalk" and dingtalk_oauth:
        user_info = await dingtalk_oauth.get_user_info(payload.code)
        sso_provider = SSOProvider.DINGTALK
    else:
        raise HTTPException(status_code=400, detail="Invalid provider")

    if not user_info:
        raise HTTPException(status_code=401, detail="SSO authentication failed")

    user = await _get_or_create_sso_user(db, user_info, sso_provider)
    return _make_tokens(user)


# ── Helper ────────────────────────────────────────────────────────────────────
async def _get_or_create_sso_user(db: AsyncSession, info: dict, provider: SSOProvider) -> User:
    email = info.get("email", "")
    sso_subject = info.get("sso_subject") or info.get("sub", "")

    result = await db.execute(
        select(User).where(
            (User.sso_provider == provider) & (User.sso_subject == sso_subject)
        )
    )
    user = result.scalar_one_or_none()

    if not user:
        username_base = email.split("@")[0].replace(".", "_")
        user = User(
            email=email,
            username=username_base,
            full_name=info.get("full_name") or info.get("name", ""),
            avatar_url=info.get("avatar_url") or info.get("picture"),
            sso_provider=provider,
            sso_subject=sso_subject,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user
