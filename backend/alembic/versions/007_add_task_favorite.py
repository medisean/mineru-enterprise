"""add task favorite flag

Revision ID: 007_add_task_favorite
Revises: 006_add_oauth2_sso_provider
Create Date: 2026-05-14
"""
from typing import Sequence, Union

from alembic import op


revision: str = "007_add_task_favorite"
down_revision: Union[str, None] = "006_add_oauth2_sso_provider"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE parse_tasks ADD COLUMN IF NOT EXISTS is_favorite BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_parse_tasks_user_favorite ON parse_tasks (user_id, is_favorite)"
    )


def downgrade() -> None:
    op.drop_index("ix_parse_tasks_user_favorite", table_name="parse_tasks")
    op.drop_column("parse_tasks", "is_favorite")
