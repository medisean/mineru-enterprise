"""
API token generation and verification.
"""
import hashlib
import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import ApiToken, User


def generate_api_token() -> str:
    return f"mru_{secrets.token_urlsafe(40)}"


def hash_api_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_prefix(token: str) -> str:
    return token[:12]


def token_suffix(token: str) -> str:
    return token[-6:]


async def authenticate_api_token(db: AsyncSession, token: str) -> User | None:
    token_hash = hash_api_token(token)
    api_token = (await db.execute(
        select(ApiToken).where(ApiToken.token_hash == token_hash, ApiToken.is_active == True)
    )).scalar_one_or_none()
    if not api_token:
        return None

    owner = (await db.execute(select(User).where(User.id == api_token.created_by_user_id))).scalar_one_or_none()
    if not owner or not owner.is_active:
        return None

    api_token.last_used_at = datetime.now(timezone.utc)
    await db.commit()
    return owner
