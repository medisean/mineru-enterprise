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
    "SELECT pg_advisory_xact_lock(hashtext('mineru_schema_compat'))",
)


async def ensure_async_schema_compat(conn: AsyncConnection) -> None:
    for statement in TASK_FAVORITE_SCHEMA_SQL:
        await conn.execute(text(statement))
    await _ensure_async_parse_task_columns(conn)
    await _ensure_async_parse_task_indexes(conn)


def ensure_sync_schema_compat(engine: Engine) -> None:
    with engine.begin() as conn:
        for statement in TASK_FAVORITE_SCHEMA_SQL:
            conn.execute(text(statement))
        _ensure_sync_parse_task_columns(conn)
        _ensure_sync_parse_task_indexes(conn)


def try_ensure_sync_schema_compat(engine: Engine, *, source: str) -> None:
    try:
        ensure_sync_schema_compat(engine)
    except Exception as exc:
        logger.warning("Runtime schema compatibility check failed", source=source, error=str(exc))


async def _ensure_async_parse_task_columns(conn: AsyncConnection) -> None:
    is_ocr_nullable = await conn.scalar(text("""
        SELECT is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'parse_tasks'
          AND column_name = 'is_ocr'
    """))
    if is_ocr_nullable == "NO":
        await conn.execute(text("ALTER TABLE parse_tasks ALTER COLUMN is_ocr DROP NOT NULL"))

    has_favorite = await conn.scalar(text("""
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'parse_tasks'
          AND column_name = 'is_favorite'
    """))
    if not has_favorite:
        await conn.execute(text("ALTER TABLE parse_tasks ADD COLUMN is_favorite BOOLEAN NOT NULL DEFAULT false"))


async def _ensure_async_parse_task_indexes(conn: AsyncConnection) -> None:
    has_index = await conn.scalar(text("""
        SELECT 1
        FROM pg_indexes
        WHERE schemaname = 'public'
          AND tablename = 'parse_tasks'
          AND indexname = 'ix_parse_tasks_user_favorite'
    """))
    if not has_index:
        await conn.execute(text("CREATE INDEX ix_parse_tasks_user_favorite ON parse_tasks (user_id, is_favorite)"))


def _ensure_sync_parse_task_columns(conn) -> None:
    is_ocr_nullable = conn.scalar(text("""
        SELECT is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'parse_tasks'
          AND column_name = 'is_ocr'
    """))
    if is_ocr_nullable == "NO":
        conn.execute(text("ALTER TABLE parse_tasks ALTER COLUMN is_ocr DROP NOT NULL"))

    has_favorite = conn.scalar(text("""
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'parse_tasks'
          AND column_name = 'is_favorite'
    """))
    if not has_favorite:
        conn.execute(text("ALTER TABLE parse_tasks ADD COLUMN is_favorite BOOLEAN NOT NULL DEFAULT false"))


def _ensure_sync_parse_task_indexes(conn) -> None:
    has_index = conn.scalar(text("""
        SELECT 1
        FROM pg_indexes
        WHERE schemaname = 'public'
          AND tablename = 'parse_tasks'
          AND indexname = 'ix_parse_tasks_user_favorite'
    """))
    if not has_index:
        conn.execute(text("CREATE INDEX ix_parse_tasks_user_favorite ON parse_tasks (user_id, is_favorite)"))
