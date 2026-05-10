"""
SQLAlchemy models.
"""
import uuid
import enum
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Text, Integer, Boolean, DateTime, Enum, ForeignKey, BigInteger, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class SSOProvider(str, enum.Enum):
    LOCAL = "local"
    OIDC = "oidc"
    OAUTH2 = "oauth2"
    LDAP = "ldap"
    WECHAT_WORK = "wechat_work"
    DINGTALK = "dingtalk"


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ─────────────────────────────────────────────────────────────────────────────
# Organization
# ─────────────────────────────────────────────────────────────────────────────
class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    quota_mb: Mapped[int] = mapped_column(Integer, default=10240)  # 10 GB default
    max_concurrent_tasks: Mapped[int] = mapped_column(Integer, default=5)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    members: Mapped[list["User"]] = relationship("User", back_populates="organization")
    tasks: Mapped[list["ParseTask"]] = relationship("ParseTask", back_populates="organization")


# ─────────────────────────────────────────────────────────────────────────────
# User
# ─────────────────────────────────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(256), unique=True, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(256), nullable=True)  # null for SSO-only users
    full_name: Mapped[str] = mapped_column(String(128), nullable=True)
    avatar_url: Mapped[str] = mapped_column(String(512), nullable=True)

    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.MEMBER)
    sso_provider: Mapped[SSOProvider] = mapped_column(Enum(SSOProvider), default=SSOProvider.LOCAL)
    sso_subject: Mapped[str] = mapped_column(String(256), nullable=True)  # external user id

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)

    organization_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("organizations.id"), nullable=True)
    organization: Mapped[Optional["Organization"]] = relationship("Organization", back_populates="members")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    tasks: Mapped[list["ParseTask"]] = relationship("ParseTask", back_populates="user")


# ─────────────────────────────────────────────────────────────────────────────
# ParseTask
# ─────────────────────────────────────────────────────────────────────────────
class ParseTask(Base):
    __tablename__ = "parse_tasks"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    celery_task_id: Mapped[str] = mapped_column(String(256), nullable=True, index=True)

    # Input file info
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    input_s3_key: Mapped[str] = mapped_column(String(1024), nullable=False)

    # Output
    output_s3_prefix: Mapped[str] = mapped_column(String(1024), nullable=True)

    # Parse config
    backend: Mapped[str] = mapped_column(String(64), default="")
    output_format: Mapped[str] = mapped_column(String(32), default="markdown")
    language: Mapped[str] = mapped_column(String(16), default="")
    is_ocr: Mapped[bool] = mapped_column(Boolean, default=False)
    enable_formula: Mapped[bool] = mapped_column(Boolean, default=True)
    enable_table: Mapped[bool] = mapped_column(Boolean, default=True)
    page_ranges: Mapped[str] = mapped_column(String(128), nullable=True)
    data_id: Mapped[str] = mapped_column(String(128), nullable=True)  # user-defined business ID
    batch_id: Mapped[str] = mapped_column(String(64), nullable=True, index=True)

    # Status
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.PENDING, index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    run_attempt: Mapped[int] = mapped_column(Integer, default=0)

    # Webhook callback
    callback_url: Mapped[str] = mapped_column(String(1024), nullable=True)       # URL to POST on completion
    callback_seed: Mapped[str] = mapped_column(String(128), nullable=True)       # HMAC seed for signature

    # Timing
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relations
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    user: Mapped["User"] = relationship("User", back_populates="tasks")
    organization_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("organizations.id"), nullable=True)
    organization: Mapped[Optional["Organization"]] = relationship("Organization", back_populates="tasks")


Index("ix_parse_tasks_user_batch", ParseTask.user_id, ParseTask.batch_id)
