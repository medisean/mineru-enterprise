"""add callback_url and callback_seed to parse_tasks

Revision ID: 003_add_callback_fields
Revises: 002_add_data_id
"""
from alembic import op
import sqlalchemy as sa

revision = "003_add_callback_fields"
down_revision = "002_add_data_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("parse_tasks", sa.Column("callback_url", sa.String(1024), nullable=True))
    op.add_column("parse_tasks", sa.Column("callback_seed", sa.String(128), nullable=True))


def downgrade() -> None:
    op.drop_column("parse_tasks", "callback_seed")
    op.drop_column("parse_tasks", "callback_url")
