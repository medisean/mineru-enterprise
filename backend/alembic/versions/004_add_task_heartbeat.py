"""Add task heartbeat fields

Revision ID: 004_add_task_heartbeat
Revises: 003_add_callback_fields
Create Date: 2026-05-10
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "004_add_task_heartbeat"
down_revision: Union[str, None] = "003_add_callback_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("parse_tasks", sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("parse_tasks", sa.Column("run_attempt", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("parse_tasks", "run_attempt")
    op.drop_column("parse_tasks", "last_heartbeat_at")
