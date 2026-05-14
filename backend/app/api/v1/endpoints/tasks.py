"""
File upload & parse task endpoints.
"""
import io
import re
import uuid
import zipfile
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, and_

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
from app.services.file_validation import validate_file_magic
from app.services.official_result_exports import FULL_ZIP_NAME, ZIP_EXPORT_DIR
from app.workers.parse_worker import dispatch_parse_task

router = APIRouter(prefix="/tasks", tags=["tasks"])


ACTIVE_QUEUE_STATUSES = (TaskStatus.PENDING, TaskStatus.PROCESSING)
RESULT_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff"}
MARKDOWN_IMAGE_PATTERN = re.compile(r"(!\[[^\]]*\]\()([^)\s]+)(\))")


async def _queued_ahead(db: AsyncSession, task: ParseTask) -> Optional[int]:
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


async def _task_out(db: AsyncSession, task: ParseTask) -> TaskOut:
    data = TaskOut.model_validate(task)
    data.queued_ahead = await _queued_ahead(db, task)
    data.is_stalled = _is_task_stalled(task)
    return data


async def _task_out_list(db: AsyncSession, tasks: list[ParseTask]) -> list[TaskOut]:
    return [await _task_out(db, task) for task in tasks]


def _is_task_stalled(task: ParseTask) -> bool:
    if task.status != TaskStatus.PROCESSING:
        return False
    marker = task.last_heartbeat_at or task.started_at
    if not marker:
        return False
    now = datetime.now(timezone.utc)
    if marker.tzinfo is None:
        marker = marker.replace(tzinfo=timezone.utc)
    return (now - marker).total_seconds() > settings.TASK_STALLED_AFTER_SECONDS


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


def _rewrite_markdown_image_urls(markdown: str, output_s3_prefix: str, image_urls: dict[str, str]) -> str:
    def replace(match: re.Match) -> str:
        prefix, src, suffix = match.groups()
        if src.startswith(("http://", "https://", "data:", "blob:", "/")):
            return match.group(0)

        normalized = src.lstrip("./")
        candidates = [
            normalized,
            normalized.split("/")[-1],
            f"{output_s3_prefix}/{normalized}",
            f"{output_s3_prefix}/{normalized.split('/')[-1]}",
        ]

        for candidate in candidates:
            url = image_urls.get(candidate)
            if url:
                return f"{prefix}{url}{suffix}"
        return match.group(0)

    return MARKDOWN_IMAGE_PATTERN.sub(replace, markdown)


def _sync_result_images_from_zip(output_s3_prefix: str, existing_keys: set[str]) -> list[dict]:
    zip_key = f"{output_s3_prefix.rstrip('/')}/{ZIP_EXPORT_DIR}/{FULL_ZIP_NAME}"
    try:
        zip_data = storage_service.download_bytes(zip_key)
    except Exception:
        return []

    synced = []
    try:
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                rel = info.filename.lstrip("/")
                filename = rel.rsplit("/", 1)[-1]
                ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
                if ext not in RESULT_IMAGE_EXTENSIONS:
                    continue
                key = f"{output_s3_prefix.rstrip('/')}/{rel}"
                if key not in existing_keys:
                    storage_service.upload_bytes(key, zf.read(info), _guess_result_content_type(filename))
                    existing_keys.add(key)
                synced.append({"key": key, "size": info.file_size, "last_modified": ""})
    except Exception:
        return []
    return synced


def _guess_result_content_type(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "bmp": "image/bmp",
        "webp": "image/webp",
        "tiff": "image/tiff",
    }.get(ext, "application/octet-stream")


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
    # Validate file content matches claimed extension (magic bytes check)
    ext = payload.original_filename.rsplit(".", 1)[-1].lower() if "." in payload.original_filename else ""
    if ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File type '.{ext}' not allowed")
    if ext:
        try:
            head = storage_service.read_head_bytes(payload.s3_key, 32)
            if head and not validate_file_magic(head, ext):
                raise HTTPException(
                    status_code=400,
                    detail=f"File content does not match the '.{ext}' extension. "
                           f"The file may be corrupted or renamed with a wrong extension.",
                )
        except HTTPException:
            raise
        except Exception:
            pass  # If S3 read fails, skip validation (file may not be uploaded yet in edge cases)

    task = ParseTask(
        original_filename=payload.original_filename,
        file_size_bytes=payload.file_size_bytes,
        input_s3_key=payload.s3_key,
        output_s3_prefix=f"results/{current_user.id}/{uuid.uuid4()}",
        backend=payload.backend,
        output_format=payload.output_format or "markdown",
        language=payload.language or "",
        is_ocr=payload.is_ocr if payload.is_ocr is not None else False,
        enable_formula=payload.enable_formula,
        enable_table=payload.enable_table,
        page_ranges=payload.page_ranges,
        data_id=payload.data_id,
        callback_url=payload.callback_url,
        callback_seed=payload.callback_seed,
        user_id=current_user.id,
        organization_id=current_user.organization_id,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    # Dispatch to Celery
    celery_task_id = dispatch_parse_task(task.id, task.input_s3_key, task.output_s3_prefix, {
        "backend": payload.backend,
        "output_format": payload.output_format or "markdown",
        "language": payload.language or "",
        "is_ocr": payload.is_ocr,
        "enable_formula": payload.enable_formula,
        "enable_table": payload.enable_table,
        "page_ranges": payload.page_ranges,
        "parse_options": payload.parse_options,
        "run_attempt": task.run_attempt,
    })
    task.celery_task_id = celery_task_id
    task.last_heartbeat_at = datetime.now(timezone.utc)
    await db.commit()

    return await _task_out(db, task)


# ── List tasks ────────────────────────────────────────────────────────────────
@router.get("/", response_model=TaskListResponse)
async def list_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str = Query(None),
    keyword: str = Query(None, description="搜索文件名"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(ParseTask).where(ParseTask.user_id == current_user.id)
    if status:
        q = q.where(ParseTask.status == TaskStatus(status))
    if keyword:
        q = q.where(ParseTask.original_filename.ilike(f"%{keyword}%"))

    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar()

    q = q.order_by(ParseTask.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    tasks = (await db.execute(q)).scalars().all()

    return TaskListResponse(items=await _task_out_list(db, tasks), total=total, page=page, page_size=page_size)


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
    return await _task_out(db, task)


# ── Get source file presigned URL (for inline preview) ─────────────────────
OFFICE_EXTENSIONS = {"pptx", "docx", "xlsx"}


@router.get("/{task_id}/source-url")
async def get_source_url(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a presigned download URL for the original uploaded file.
    For Office files, returns the converted PDF preview if available."""
    task = await db.get(ParseTask, task_id)
    if not task or task.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Task not found")

    ext = task.original_filename.rsplit(".", 1)[-1].lower() if "." in task.original_filename else ""
    is_office = ext in OFFICE_EXTENSIONS

    # For Office files, try to find the converted PDF preview first
    if is_office and task.output_s3_prefix:
        preview_key = f"{task.output_s3_prefix}/_preview/source_preview.pdf"
        try:
            # Check if the PDF preview exists in S3
            objects = storage_service.list_objects(f"{task.output_s3_prefix}/_preview/")
            for obj in objects:
                if obj["key"] == preview_key:
                    url = storage_service.generate_download_presigned_url(
                        preview_key,
                        filename=task.original_filename.rsplit(".", 1)[0] + ".pdf",
                        inline_disposition=True,
                    )
                    return {"download_url": url, "preview_type": "pdf"}
        except Exception:
            pass

    # Fallback: return the original file URL
    url = storage_service.generate_download_presigned_url(
        task.input_s3_key,
        filename=task.original_filename,
        inline_disposition=True,
    )
    return {"download_url": url, "preview_type": "original"}


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


# ── Batch download as ZIP ────────────────────────────────────────────────────
class BatchDownloadRequest(BaseModel):
    task_ids: List[str]


@router.post("/batch/download")
async def batch_download(
    payload: BatchDownloadRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Download parsed Markdown files from multiple tasks as a ZIP archive.
    Returns a presigned URL for the generated ZIP file.
    """
    if not payload.task_ids:
        raise HTTPException(status_code=400, detail="No task IDs provided")

    # Fetch all requested tasks belonging to the user
    result = await db.execute(
        select(ParseTask).where(
            ParseTask.id.in_(payload.task_ids),
            ParseTask.user_id == current_user.id,
            ParseTask.status == TaskStatus.SUCCESS,
        )
    )
    tasks = result.scalars().all()

    if not tasks:
        raise HTTPException(status_code=400, detail="No completed tasks found")

    # Build ZIP in memory
    zip_buffer = io.BytesIO()
    filename_counter: dict[str, int] = {}

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for task in tasks:
            objects = storage_service.list_objects(task.output_s3_prefix)
            # Find markdown file(s)
            md_files = [obj for obj in objects if obj["key"].endswith(".md")]
            # If no .md, take the first file
            target_files = md_files if md_files else (objects[:1] if objects else [])

            for obj in target_files:
                original_name = obj["key"].split("/")[-1]
                # Build a friendly filename: <task_filename_base>/<original_name>
                base_name = task.original_filename.rsplit(".", 1)[0] if "." in task.original_filename else task.original_filename

                # Handle duplicate folder names
                if base_name in filename_counter:
                    filename_counter[base_name] += 1
                    base_name = f"{base_name}_{filename_counter[base_name]}"
                else:
                    filename_counter[base_name] = 0

                arcname = f"{base_name}/{original_name}"
                content = storage_service.download_bytes(obj["key"])
                zf.writestr(arcname, content)

    zip_buffer.seek(0)
    zip_data = zip_buffer.read()

    # Upload ZIP to S3
    zip_filename = f"MinerU_Batch_Export_{datetime.now().strftime('%Y%m%d%H%M%S')}.zip"
    zip_key = f"downloads/{current_user.id}/{uuid.uuid4()}/{zip_filename}"
    storage_service.upload_bytes(zip_key, zip_data, content_type="application/zip")

    # Generate presigned download URL (15 min expiry)
    download_url = storage_service.generate_download_presigned_url(
        zip_key, expires=900, filename=zip_filename
    )

    return {
        "download_url": download_url,
        "task_count": len(tasks),
        "zip_size": len(zip_data),
    }


# ── Retry a failed/cancelled/stalled task ───────────────────────────────────
@router.post("/{task_id}/retry", response_model=TaskOut)
async def retry_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retry a failed, cancelled, or stalled task — resets status and re-dispatches to Celery."""
    task = await db.get(ParseTask, task_id)
    if not task or task.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status not in (TaskStatus.FAILED, TaskStatus.CANCELLED) and not _is_task_stalled(task):
        raise HTTPException(status_code=400, detail="Only failed, cancelled, or stalled tasks can be retried")

    if task.status in (TaskStatus.PENDING, TaskStatus.PROCESSING) and task.celery_task_id:
        try:
            from app.workers.parse_worker import celery_app
            celery_app.control.revoke(task.celery_task_id, terminate=True, signal="SIGTERM")
        except Exception:
            pass

    # Reset task state
    task.status = TaskStatus.PENDING
    task.progress = 0
    task.error_message = None
    task.started_at = None
    task.completed_at = None
    task.last_heartbeat_at = None
    task.run_attempt = (task.run_attempt or 0) + 1
    # Generate a fresh output prefix so old results don't collide
    task.output_s3_prefix = f"results/{current_user.id}/{uuid.uuid4()}"
    task.celery_task_id = None
    await db.commit()
    await db.refresh(task)

    # Re-dispatch to Celery
    celery_task_id = _dispatch_existing_task(task)
    task.celery_task_id = celery_task_id
    task.last_heartbeat_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(task)

    return await _task_out(db, task)


# ── Stop task without deleting record ────────────────────────────────────────
@router.post("/{task_id}/cancel", response_model=TaskOut)
async def cancel_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    task = await db.get(ParseTask, task_id)
    if not task or task.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status not in (TaskStatus.PENDING, TaskStatus.PROCESSING):
        raise HTTPException(status_code=400, detail="Only pending or processing tasks can be stopped")

    if task.celery_task_id:
        try:
            from app.workers.parse_worker import celery_app
            celery_app.control.revoke(task.celery_task_id, terminate=True, signal="SIGTERM")
        except Exception:
            pass

    task.status = TaskStatus.CANCELLED
    task.error_message = "用户手动停止任务"
    task.progress = min(task.progress or 0, 99)
    task.completed_at = datetime.now(timezone.utc)
    task.last_heartbeat_at = None
    task.run_attempt = (task.run_attempt or 0) + 1
    await db.commit()
    await db.refresh(task)
    return await _task_out(db, task)


# ── Cancel task ───────────────────────────────────────────────────────────────
@router.delete("/{task_id}")
async def delete_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a task. Cancels if running, then removes from DB. S3 files are kept."""
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

    # Remove from DB (S3 files are kept intentionally)
    await db.delete(task)
    await db.commit()
    return {"message": "Task deleted"}


# ── Batch presigned upload URLs ───────────────────────────────────────────
@router.post("/batch/upload-urls")
async def batch_get_upload_urls(
    payloads: List[PresignedUploadRequest],
    current_user: User = Depends(get_current_user),
):
    """Get presigned upload URLs for up to MAX_BATCH_FILES files at once."""
    if len(payloads) > settings.MAX_BATCH_FILES:
        raise HTTPException(status_code=400, detail=f"Maximum {settings.MAX_BATCH_FILES} files per batch upload")

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
    """Create multiple parse tasks at once."""
    if len(payloads) > settings.MAX_BATCH_FILES:
        raise HTTPException(status_code=400, detail=f"Maximum {settings.MAX_BATCH_FILES} tasks per batch")

    # Validate file content for all payloads (magic bytes check)
    for payload in payloads:
        ext = payload.original_filename.rsplit(".", 1)[-1].lower() if "." in payload.original_filename else ""
        if ext not in settings.ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"File type '.{ext}' not allowed for '{payload.original_filename}'")
        if ext:
            try:
                head = storage_service.read_head_bytes(payload.s3_key, 32)
                if head and not validate_file_magic(head, ext):
                    raise HTTPException(
                        status_code=400,
                        detail=f"File '{payload.original_filename}' content does not match the '.{ext}' extension.",
                    )
            except HTTPException:
                raise
            except Exception:
                pass

    created = []
    for payload in payloads:
        task = ParseTask(
            original_filename=payload.original_filename,
            file_size_bytes=payload.file_size_bytes,
            input_s3_key=payload.s3_key,
            output_s3_prefix=f"results/{current_user.id}/{uuid.uuid4()}",
            backend=payload.backend,
            output_format=payload.output_format or "markdown",
            language=payload.language or "",
            is_ocr=payload.is_ocr if payload.is_ocr is not None else False,
            enable_formula=payload.enable_formula,
            enable_table=payload.enable_table,
            page_ranges=payload.page_ranges,
            data_id=payload.data_id,
            callback_url=payload.callback_url,
            callback_seed=payload.callback_seed,
            user_id=current_user.id,
            organization_id=current_user.organization_id,
        )
        db.add(task)
        created.append(task)

    # Flush to assign IDs without committing yet
    await db.flush()

    # Dispatch Celery tasks using the flushed task IDs
    for task, payload in zip(created, payloads):
        celery_task_id = dispatch_parse_task(task.id, task.input_s3_key, task.output_s3_prefix, {
            "backend": payload.backend,
            "output_format": payload.output_format or "markdown",
            "language": payload.language or "",
            "is_ocr": payload.is_ocr,
            "enable_formula": payload.enable_formula,
            "enable_table": payload.enable_table,
            "page_ranges": payload.page_ranges,
            "parse_options": payload.parse_options,
            "run_attempt": task.run_attempt,
        })
        task.celery_task_id = celery_task_id
        task.last_heartbeat_at = datetime.now(timezone.utc)

    await db.commit()

    # Refresh all tasks to get committed state
    all_tasks = []
    for task in created:
        await db.refresh(task)
        all_tasks.append(task)

    return {"items": await _task_out_list(db, all_tasks), "total": len(all_tasks)}


# ── Get task result preview (Markdown + JSON content) ───────────────────
@router.get("/{task_id}/preview")
async def get_task_preview(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return Markdown and JSON content for inline preview."""
    task = await db.get(ParseTask, task_id)
    if not task or task.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != TaskStatus.SUCCESS:
        raise HTTPException(status_code=400, detail=f"Task not completed (status: {task.status})")

    objects = storage_service.list_objects(task.output_s3_prefix)

    markdown_content = None
    json_content = None
    html_content = None

    for obj in objects:
        key = obj["key"]
        if key.endswith(".md") and markdown_content is None:
            content = storage_service.download_bytes(key)
            markdown_content = content.decode("utf-8", errors="replace")
        elif key.endswith(".json") and "content_list" in key and json_content is None:
            content = storage_service.download_bytes(key)
            json_content = content.decode("utf-8", errors="replace")
        elif key.endswith(".html") and html_content is None:
            content = storage_service.download_bytes(key)
            html_content = content.decode("utf-8", errors="replace")

    # If no markdown but html exists, use html as markdown_content
    if not markdown_content and html_content:
        markdown_content = html_content

    # Post-process: convert HTML tables to Markdown tables
    # MinerU office backend outputs raw HTML tables in .md files;
    # converting them makes the right panel render cleanly.
    if markdown_content:
        from app.services.markdown_utils import convert_html_tables_to_markdown
        markdown_content = convert_html_tables_to_markdown(markdown_content)
        object_keys = {obj["key"] for obj in objects}
        objects.extend(_sync_result_images_from_zip(task.output_s3_prefix, object_keys))
        image_urls = {}
        for obj in objects:
            key = obj["key"]
            filename = key.rsplit("/", 1)[-1]
            ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            if ext in RESULT_IMAGE_EXTENSIONS:
                url = storage_service.generate_download_presigned_url(
                    key,
                    filename=filename,
                    inline_disposition=True,
                )
                image_urls[key] = url
                image_urls[filename] = url
        markdown_content = _rewrite_markdown_image_urls(markdown_content, task.output_s3_prefix, image_urls)

    # Determine primary format for backwards compat
    if markdown_content:
        primary_format = "html" if html_content and not any(k.endswith(".md") for k in [o["key"] for o in objects]) else "markdown"
    elif json_content:
        primary_format = "json"
    else:
        primary_format = "raw"

    # Fallback: return first file as raw
    if not markdown_content and not json_content and objects:
        content = storage_service.download_bytes(objects[0]["key"])
        return {
            "format": "raw",
            "filename": objects[0]["key"].split("/")[-1],
            "content": content.decode("utf-8", errors="replace"),
            "markdown_content": None,
            "json_content": None,
        }

    return {
        "format": primary_format,
        "content": markdown_content or json_content,
        "markdown_content": markdown_content,
        "json_content": json_content,
    }
