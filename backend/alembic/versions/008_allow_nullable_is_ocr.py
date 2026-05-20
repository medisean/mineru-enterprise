"""Allow automatic OCR mode for parse tasks.

Revision ID: 008_allow_nullable_is_ocr
Revises: 007_add_task_favorite
Create Date: 2026-05-20
"""
from typing import Union

from alembic import op


revision: str = "008_allow_nullable_is_ocr"
down_revision: Union[str, None] = "007_add_task_favorite"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE parse_tasks ALTER COLUMN is_ocr DROP NOT NULL")


def downgrade() -> None:
    op.execute("UPDATE parse_tasks SET is_ocr = false WHERE is_ocr IS NULL")
    op.execute("ALTER TABLE parse_tasks ALTER COLUMN is_ocr SET NOT NULL")
