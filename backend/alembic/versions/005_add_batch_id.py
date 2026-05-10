"""Add batch_id to parse_tasks

Revision ID: 005_add_batch_id
Revises: 004_add_task_heartbeat
Create Date: 2026-05-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "005_add_batch_id"
down_revision: Union[str, None] = "004_add_task_heartbeat"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("parse_tasks", sa.Column("batch_id", sa.String(length=64), nullable=True))
    op.create_index("ix_parse_tasks_batch_id", "parse_tasks", ["batch_id"])
    op.create_index("ix_parse_tasks_user_batch", "parse_tasks", ["user_id", "batch_id"])


def downgrade() -> None:
    op.drop_index("ix_parse_tasks_user_batch", table_name="parse_tasks")
    op.drop_index("ix_parse_tasks_batch_id", table_name="parse_tasks")
    op.drop_column("parse_tasks", "batch_id")
