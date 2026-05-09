"""Add data_id column to parse_tasks

Revision ID: 002_add_data_id
Revises: 001_init
Create Date: 2026-05-02
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "002_add_data_id"
down_revision: Union[str, None] = "001_init"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "parse_tasks",
        sa.Column("data_id", sa.String(128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("parse_tasks", "data_id")
