"""
Database setup — async SQLAlchemy with PostgreSQL.
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings
from app.core.schema_compat import ensure_async_schema_compat

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    echo=settings.DEBUG,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def init_db():
    async with engine.begin() as conn:
        # Serialize first-run DDL across uvicorn workers so PostgreSQL enum creation cannot race.
        await conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('mineru_schema_compat'))"))
        await conn.run_sync(Base.metadata.create_all)
        await ensure_async_schema_compat(conn)


async def get_db() -> AsyncSession:
    """Provide a transactional scope for API endpoints.

    IMPORTANT: Auto-commit is intentionally NOT performed here.
    Each write endpoint must call `await db.commit()` explicitly.
    Read-only endpoints (GET) will simply yield the session and close it.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
