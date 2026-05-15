"""
Runtime schema compatibility helpers.

The project still supports existing installations that were created before
Alembic migrations were consistently applied. These DDL statements are
intentionally idempotent so API and worker processes can run them safely.
"""
import structlog
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncConnection

logger = structlog.get_logger(__name__)


TASK_FAVORITE_SCHEMA_SQL = (
    "ALTER TABLE parse_tasks ADD COLUMN IF NOT EXISTS is_favorite BOOLEAN NOT NULL DEFAULT false",
    "CREATE INDEX IF NOT EXISTS ix_parse_tasks_user_favorite ON parse_tasks (user_id, is_favorite)",
)


async def ensure_async_schema_compat(conn: AsyncConnection) -> None:
    for statement in TASK_FAVORITE_SCHEMA_SQL:
        await conn.execute(text(statement))


def ensure_sync_schema_compat(engine: Engine) -> None:
    with engine.begin() as conn:
        for statement in TASK_FAVORITE_SCHEMA_SQL:
            conn.execute(text(statement))


def try_ensure_sync_schema_compat(engine: Engine, *, source: str) -> None:
    try:
        ensure_sync_schema_compat(engine)
    except Exception as exc:
        logger.warning("Runtime schema compatibility check failed", source=source, error=str(exc))
