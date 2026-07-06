"""
Background watchdog for parse tasks that stopped heartbeating or lost queue delivery.
"""
import asyncio
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy import text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.models import ParseTask, TaskStatus
from app.workers.parse_worker import dispatch_parse_task

logger = structlog.get_logger(__name__)


def _has_parse_attempts_remaining(task: ParseTask) -> bool:
    return (task.run_attempt or 0) < max(settings.TASK_MAX_PARSE_ATTEMPTS - 1, 0)


def _seconds_since(dt: datetime | None) -> float:
    if not dt:
        return 0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds()


async def fail_stalled_tasks_once() -> int:
    cutoff_seconds = settings.TASK_STALLED_AFTER_SECONDS
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ParseTask).where(ParseTask.status == TaskStatus.PROCESSING)
            .with_for_update(skip_locked=True)
        )
        stalled = []
        for task in result.scalars().all():
            marker = task.last_heartbeat_at or task.started_at
            if _seconds_since(marker) > cutoff_seconds:
                stalled.append(task)

        for task in stalled:
            task.status = TaskStatus.FAILED
            task.error_message = f"任务超过 {cutoff_seconds} 秒无心跳，已自动标记为失败"
            task.completed_at = datetime.now(timezone.utc)
            task.last_heartbeat_at = None
            task.run_attempt = (task.run_attempt or 0) + 1
            if task.celery_task_id:
                try:
                    from app.workers.parse_worker import celery_app
                    celery_app.control.revoke(task.celery_task_id, terminate=True, signal="SIGTERM")
                except Exception as exc:
                    logger.warning("Failed to revoke stalled task", task_id=task.id, error=str(exc))

        if stalled:
            await db.commit()
            logger.warning("Marked stalled tasks as failed", count=len(stalled))
        return len(stalled)


def _dispatch_existing_task(task: ParseTask) -> str:
    return dispatch_parse_task(task.id, task.input_s3_key, task.output_s3_prefix, {
        "backend": task.backend,
        "output_format": task.output_format,
        "language": task.language,
        "is_ocr": task.is_ocr,
        "enable_formula": task.enable_formula,
        "enable_table": task.enable_table,
        "page_ranges": task.page_ranges,
        "parse_options": None,
        "run_attempt": task.run_attempt,
    })


async def redispatch_stale_pending_tasks_once() -> int:
    cutoff_seconds = settings.TASK_PENDING_STALLED_AFTER_SECONDS
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ParseTask).where(TaskStatus.PENDING == ParseTask.status)
            .with_for_update(skip_locked=True)
        )
        stale = []
        for task in result.scalars().all():
            marker = task.last_heartbeat_at or task.created_at
            if _seconds_since(marker) > cutoff_seconds:
                stale.append(task)

        for task in stale:
            if not _has_parse_attempts_remaining(task):
                task.status = TaskStatus.FAILED
                task.error_message = f"连续 {settings.TASK_MAX_PARSE_ATTEMPTS} 次解析未成功，已停止自动解析"
                task.completed_at = datetime.now(timezone.utc)
                task.last_heartbeat_at = None
                continue
            task.run_attempt = (task.run_attempt or 0) + 1
            task.output_s3_prefix = task.output_s3_prefix or f"results/{task.user_id}/{uuid.uuid4()}"
            task.celery_task_id = _dispatch_existing_task(task)
            task.error_message = None
            task.last_heartbeat_at = datetime.now(timezone.utc)

        if stale:
            await db.commit()
            logger.warning("Redispatched stale pending tasks", count=len(stale))
        return len(stale)


async def watchdog_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            async with AsyncSessionLocal() as lock_db:
                locked = await lock_db.execute(
                    text("SELECT pg_try_advisory_lock(hashtext('mineru_task_watchdog'))")
                )
                if locked.scalar_one():
                    try:
                        await fail_stalled_tasks_once()
                        await redispatch_stale_pending_tasks_once()
                    finally:
                        await lock_db.execute(
                            text("SELECT pg_advisory_unlock(hashtext('mineru_task_watchdog'))")
                        )
        except Exception as exc:
            logger.warning("Task watchdog scan failed", error=str(exc))
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.TASK_WATCHDOG_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass
