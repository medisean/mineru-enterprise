"""
WebSocket endpoint for real-time task progress.
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio
import json
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, and_

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import decode_token
from app.models.models import ParseTask, TaskStatus

router = APIRouter(prefix="/ws", tags=["websocket"])


async def _queued_ahead(db: AsyncSession, task: ParseTask) -> int | None:
    if task.status != TaskStatus.PENDING:
        return None
    conditions = [
        or_(
            ParseTask.status == TaskStatus.PROCESSING,
            and_(ParseTask.status == TaskStatus.PENDING, ParseTask.created_at < task.created_at),
        ),
    ]
    count = await db.scalar(select(func.count(ParseTask.id)).where(*conditions))
    return int(count or 0)


def _is_task_stalled(task: ParseTask) -> bool:
    if task.status != TaskStatus.PROCESSING:
        return False
    marker = task.last_heartbeat_at or task.started_at
    if not marker:
        return False
    if marker.tzinfo is None:
        marker = marker.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - marker).total_seconds() > settings.TASK_STALLED_AFTER_SECONDS


@router.websocket("/tasks/{task_id}")
async def task_progress_ws(websocket: WebSocket, task_id: str):
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001)
        return

    payload = decode_token(token)
    if not payload:
        await websocket.close(code=4001)
        return

    user_id = payload.get("sub")
    await websocket.accept()

    try:
        while True:
            async with AsyncSessionLocal() as db:
                task = await db.get(ParseTask, task_id)
                if not task or task.user_id != user_id:
                    await websocket.send_json({"error": "Task not found"})
                    break

                await websocket.send_json({
                    "task_id": task_id,
                    "status": task.status.value,
                    "progress": task.progress,
                    "queued_ahead": await _queued_ahead(db, task),
                    "is_stalled": _is_task_stalled(task),
                    "last_heartbeat_at": task.last_heartbeat_at.isoformat() if task.last_heartbeat_at else None,
                    "error": task.error_message,
                })

                if task.status.value in ("success", "failed", "cancelled"):
                    break

            await asyncio.sleep(2)
    except WebSocketDisconnect:
        pass
