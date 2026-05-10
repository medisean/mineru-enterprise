"""add oauth2 sso provider

Revision ID: 006_add_oauth2_sso_provider
Revises: 005_add_batch_id
Create Date: 2026-05-10
"""
from typing import Sequence, Union

from alembic import op


revision: str = "006_add_oauth2_sso_provider"
down_revision: Union[str, None] = "005_add_batch_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'ssoprovider') THEN
                ALTER TYPE ssoprovider ADD VALUE IF NOT EXISTS 'oauth2';
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # PostgreSQL cannot drop enum values safely without recreating the type.
    pass
