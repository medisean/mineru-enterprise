"""
File upload & parse task endpoints.
"""
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.config import settings
from app.models.models import User, ParseTask, TaskStatus
from app.schemas.schemas import (
    PresignedUploadRequest, PresignedUploadResponse,
    CreateTaskRequest, TaskOut, TaskListResponse,
    TaskResultResponse, TaskResultFile,
)
from app.services.storage import storage_service
from app.workers.parse_worker import parse_document

router = APIRouter(prefix="/tasks", tags=["tasks"])


# ── Step 1: Request presigned upload URL ─────────────────────────────────────
@router.post("/upload-url", response_model=PresignedUploadResponse)
async def get_upload_url(
    payload: PresignedUploadRequest,
    current_user: User = Depends(get_current_user),
):
    ext = payload.filename.rsplit(".", 1)[-1].lower() if "." in payload.filename else ""
    if ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File type '.{ext}' not allowed")

    if payload.file_size_bytes > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"File too large (max {settings.MAX_UPLOAD_SIZE_MB} MB)")

    s3_key = f"uploads/{current_user.id}/{uuid.uuid4()}/{payload.filename}"
    url = storage_service.generate_upload_presigned_url(s3_key, payload.content_type)

    return PresignedUploadResponse(
        upload_url=url,
        s3_key=s3_key,
        expires_in=settings.S3_PRESIGN_EXPIRE_SECONDS,
    )


# ── Step 2: Create parse task (called after upload completes) ─────────────────
@router.post("/", response_model=TaskOut)
async def create_task(
    payload: CreateTaskRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    task = ParseTask(
        original_filename=payload.original_filename,
        file_size_bytes=payload.file_size_bytes,
        input_s3_key=payload.s3_key,
        output_s3_prefix=f"results/{current_user.id}/{uuid.uuid4()}",
        backend=payload.backend,
        output_format=payload.output_format,
        language=payload.language or "ch",
        is_ocr=payload.is_ocr if payload.is_ocr is not None else False,
        enable_formula=payload.enable_formula,
        enable_table=payload.enable_table,
        page_ranges=payload.page_ranges,
        user_id=current_user.id,
        organization_id=current_user.organization_id,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    # Dispatch to Celery
    celery_task = parse_document.apply_async(
        args=[task.id, task.input_s3_key, task.output_s3_prefix, {
            "backend": payload.backend,
            "output_format": payload.output_format,
            "language": payload.language or "ch",
            "is_ocr": payload.is_ocr,
            "enable_formula": payload.enable_formula,
            "enable_table": payload.enable_table,
            "page_ranges": payload.page_ranges,
            "parse_options": payload.parse_options,
        }],
        queue="parse",
    )
    task.celery_task_id = celery_task.id
    await db.commit()

    return task


# ── List tasks ────────────────────────────────────────────────────────────────
@router.get("/", response_model=TaskListResponse)
async def list_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(ParseTask).where(ParseTask.user_id == current_user.id)
    if status:
        q = q.where(ParseTask.status == TaskStatus(status))

    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar()

    q = q.order_by(ParseTask.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    tasks = (await db.execute(q)).scalars().all()

    return TaskListResponse(items=tasks, total=total, page=page, page_size=page_size)


# ── Get single task ───────────────────────────────────────────────────────────
@router.get("/{task_id}", response_model=TaskOut)
async def get_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    task = await db.get(ParseTask, task_id)
    if not task or task.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


# ── Get task results (download links) ────────────────────────────────────────
@router.get("/{task_id}/results", response_model=TaskResultResponse)
async def get_task_results(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    task = await db.get(ParseTask, task_id)
    if not task or task.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != TaskStatus.SUCCESS:
        raise HTTPException(status_code=400, detail=f"Task not completed (status: {task.status})")

    objects = storage_service.list_objects(task.output_s3_prefix)
    files = []
    for obj in objects:
        filename = obj["key"].split("/")[-1]
        files.append(TaskResultFile(
            filename=filename,
            s3_key=obj["key"],
            download_url=storage_service.generate_download_presigned_url(obj["key"], filename=filename),
            size=obj["size"],
        ))

    return TaskResultResponse(task_id=task_id, status=task.status.value, files=files)


# ── Retry a failed/cancelled task ─────────────────────────────────────────
@router.post("/{task_id}/retry", response_model=TaskOut)
async def retry_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retry a failed or cancelled task — resets status and re-dispatches to Celery."""
    task = await db.get(ParseTask, task_id)
    if not task or task.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status not in (TaskStatus.FAILED, TaskStatus.CANCELLED):
        raise HTTPException(status_code=400, detail="Only failed or cancelled tasks can be retried")

    # Reset task state
    task.status = TaskStatus.PENDING
    task.progress = 0
    task.error_message = None
    task.started_at = None
    task.completed_at = None
    # Generate a fresh output prefix so old results don't collide
    task.output_s3_prefix = f"results/{current_user.id}/{uuid.uuid4()}"
    task.celery_task_id = None
    await db.commit()
    await db.refresh(task)

    # Re-dispatch to Celery
    celery_task = parse_document.apply_async(
        args=[task.id, task.input_s3_key, task.output_s3_prefix, {
            "backend": task.backend,
            "output_format": task.output_format,
            "language": task.language,
            "is_ocr": task.is_ocr,
            "enable_formula": task.enable_formula,
            "enable_table": task.enable_table,
            "page_ranges": task.page_ranges,
            "parse_options": None,
        }],
        queue="parse",
    )
    task.celery_task_id = celery_task.id
    await db.commit()
    await db.refresh(task)

    return task


# ── Cancel task ───────────────────────────────────────────────────────────────
@router.delete("/{task_id}")
async def delete_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a task. Cancels if running, then removes from DB and S3."""
    task = await db.get(ParseTask, task_id)
    if not task or task.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Task not found")

    # If still running, revoke the Celery task first
    if task.status in (TaskStatus.PENDING, TaskStatus.PROCESSING) and task.celery_task_id:
        try:
            from app.workers.parse_worker import celery_app
            celery_app.control.revoke(task.celery_task_id, terminate=True)
        except Exception:
            pass

    # Clean up S3 objects
    if task.output_s3_prefix:
        try:
            objects = storage_service.list_objects(task.output_s3_prefix)
            for obj in objects:
                storage_service.delete_object(obj["key"])
        except Exception:
            pass

    # Delete uploaded source file
    if task.input_s3_key:
        try:
            storage_service.delete_object(task.input_s3_key)
        except Exception:
            pass

    # Remove from DB
    await db.delete(task)
    await db.commit()
    return {"message": "Task deleted"}


# ── Batch presigned upload URLs ───────────────────────────────────────────
@router.post("/batch/upload-urls")
async def batch_get_upload_urls(
    payloads: List[PresignedUploadRequest],
    current_user: User = Depends(get_current_user),
):
    """Get presigned upload URLs for up to 50 files at once (mirrors MinerU batch API)."""
    if len(payloads) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 files per batch upload")

    results = []
    for p in payloads:
        ext = p.filename.rsplit(".", 1)[-1].lower() if "." in p.filename else ""
        if ext not in settings.ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"File type '.{ext}' not allowed for '{p.filename}'")
        if p.file_size_bytes > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
            raise HTTPException(status_code=400, detail=f"File too large (max {settings.MAX_UPLOAD_SIZE_MB} MB): '{p.filename}'")

        s3_key = f"uploads/{current_user.id}/{uuid.uuid4()}/{p.filename}"
        url = storage_service.generate_upload_presigned_url(s3_key, p.content_type)
        results.append({
            "filename": p.filename,
            "upload_url": url,
            "s3_key": s3_key,
            "expires_in": settings.S3_PRESIGN_EXPIRE_SECONDS,
        })

    return {"items": results, "total": len(results)}


# ── Batch create tasks ───────────────────────────────────────────────────
@router.post("/batch/tasks")
async def batch_create_tasks(
    payloads: List[CreateTaskRequest],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create multiple parse tasks at once (up to 200 files, matching MinerU API limits)."""
    if len(payloads) > 200:
        raise HTTPException(status_code=400, detail="Maximum 200 tasks per batch")

    created = []
    for payload in payloads:
        task = ParseTask(
            original_filename=payload.original_filename,
            file_size_bytes=payload.file_size_bytes,
            input_s3_key=payload.s3_key,
            output_s3_prefix=f"results/{current_user.id}/{uuid.uuid4()}",
            backend=payload.backend,
            output_format=payload.output_format,
            language=payload.language or "ch",
            is_ocr=payload.is_ocr if payload.is_ocr is not None else False,
            enable_formula=payload.enable_formula,
            enable_table=payload.enable_table,
            page_ranges=payload.page_ranges,
            user_id=current_user.id,
            organization_id=current_user.organization_id,
        )
        db.add(task)

    await db.commit()

    # Refresh all and dispatch Celery
    for task_id, payload in zip([t.id for t in created] if created else [], payloads):
        pass  # tasks are already in DB, we need to fetch them

    # Re-query created tasks
    all_tasks = []
    for payload in payloads:
        # Get the most recently created task for this file
        q = select(ParseTask).where(
            ParseTask.user_id == current_user.id,
            ParseTask.original_filename == payload.original_filename,
            ParseTask.input_s3_key == payload.s3_key,
        ).order_by(ParseTask.created_at.desc()).limit(1)
        result = await db.execute(q)
        task = result.scalar_one_or_none()
        if task:
            celery_task = parse_document.apply_async(
                args=[task.id, task.input_s3_key, task.output_s3_prefix, {
                    "backend": payload.backend,
                    "output_format": payload.output_format,
                    "language": payload.language or "ch",
                    "is_ocr": payload.is_ocr,
                    "enable_formula": payload.enable_formula,
                    "enable_table": payload.enable_table,
                    "page_ranges": payload.page_ranges,
                    "parse_options": payload.parse_options,
                }],
                queue="parse",
            )
            task.celery_task_id = celery_task.id
            all_tasks.append(task)

    await db.commit()
    return {"items": [TaskOut.model_validate(t) for t in all_tasks], "total": len(all_tasks)}


# ── Get task result preview (Markdown content) ───────────────────────────
@router.get("/{task_id}/preview")
async def get_task_preview(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return raw Markdown/JSON content for inline preview (no download)."""
    task = await db.get(ParseTask, task_id)
    if not task or task.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != TaskStatus.SUCCESS:
        raise HTTPException(status_code=400, detail=f"Task not completed (status: {task.status})")

    objects = storage_service.list_objects(task.output_s3_prefix)
    for obj in objects:
        key = obj["key"]
        if key.endswith(".md"):
            content = storage_service.download_bytes(key)
            return {"format": "markdown", "content": content.decode("utf-8", errors="replace")}
        elif key.endswith(".json") and "content_list" in key:
            content = storage_service.download_bytes(key)
            return {"format": "json", "content": content.decode("utf-8", errors="replace")}
        elif key.endswith(".html"):
            content = storage_service.download_bytes(key)
            return {"format": "html", "content": content.decode("utf-8", errors="replace")}

    # Fallback: return first file
    if objects:
        content = storage_service.download_bytes(objects[0]["key"])
        return {"format": "raw", "filename": objects[0]["key"].split("/")[-1], "content": content.decode("utf-8", errors="replace")}

    raise HTTPException(status_code=404, detail="No previewable content found")
