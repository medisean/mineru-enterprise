"""Initial schema + enhanced parse options

Revision ID: 001_init
Revises:
Create Date: 2026-04-29
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "001_init"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # organizations
    op.create_table(
        "organizations",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("slug", sa.String(64), unique=True, nullable=False),
        sa.Column("quota_mb", sa.Integer, server_default="10240"),
        sa.Column("max_concurrent_tasks", sa.Integer, server_default="5"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # users
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("email", sa.String(256), unique=True, nullable=False, index=True),
        sa.Column("username", sa.String(64), unique=True, nullable=False),
        sa.Column("hashed_password", sa.String(256), nullable=True),
        sa.Column("full_name", sa.String(128), nullable=True),
        sa.Column("avatar_url", sa.String(512), nullable=True),
        sa.Column("role", sa.String(16), server_default="member"),
        sa.Column("sso_provider", sa.String(16), server_default="local"),
        sa.Column("sso_subject", sa.String(256), nullable=True),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("is_superuser", sa.Boolean, server_default="false"),
        sa.Column("organization_id", UUID(as_uuid=False), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )

    # parse_tasks
    op.create_table(
        "parse_tasks",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("celery_task_id", sa.String(256), nullable=True, index=True),
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger, server_default="0"),
        sa.Column("input_s3_key", sa.String(1024), nullable=False),
        sa.Column("output_s3_prefix", sa.String(1024), nullable=True),
        sa.Column("output_format", sa.String(32), server_default="markdown"),
        sa.Column("backend", sa.String(64), server_default="pipeline"),
        sa.Column("language", sa.String(16), server_default="ch"),
        sa.Column("is_ocr", sa.Boolean, server_default="false"),
        sa.Column("enable_formula", sa.Boolean, server_default="true"),
        sa.Column("enable_table", sa.Boolean, server_default="true"),
        sa.Column("page_ranges", sa.String(128), nullable=True),
        sa.Column("status", sa.String(16), server_default="pending", index=True),
        sa.Column("progress", sa.Integer, server_default="0"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("organization_id", UUID(as_uuid=False), sa.ForeignKey("organizations.id"), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("parse_tasks")
    op.drop_table("users")
    op.drop_table("organizations")
