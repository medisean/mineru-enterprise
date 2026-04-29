"""
WebSocket endpoint for real-time task progress.
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import decode_token
from app.models.models import ParseTask

router = APIRouter(prefix="/ws", tags=["websocket"])


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
                    "error": task.error_message,
                })

                if task.status.value in ("success", "failed", "cancelled"):
                    break

            await asyncio.sleep(2)
    except WebSocketDisconnect:
        pass
