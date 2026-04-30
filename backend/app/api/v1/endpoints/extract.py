"""
MinerU Official API Compatible Endpoints — Precision Extract API (v4).
Matches the official API at https://mineru.net/apiManage/docs

Endpoints:
  POST /api/v4/extract/task              — Single file parse by URL
  GET  /api/v4/extract/task/{task_id}    — Get single task result
  POST /api/v4/file-urls/batch           — Batch local file upload (presigned URLs)
  POST /api/v4/extract/task/batch        — Batch URL parse
  GET  /api/v4/extract-results/batch/{batch_id} — Batch results
"""
import uuid
import time
import structlog
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.config import settings
from app.models.models import User, ParseTask, TaskStatus
from app.schemas.schemas import (
    ExtractTaskRequest, ExtractTaskResultData, ExtractProgress,
    BatchFileUrlsRequest, BatchFileUrlsData,
    BatchUrlExtractRequest, BatchUrlExtractData,
    BatchExtractResultData, BatchExtractResultItem,
)
from app.services.storage import storage_service
from app.workers.parse_worker import dispatch_parse_task

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v4", tags=["MinerU Precision API"])


# ── Internal status mapper ──────────────────────────────────────────────────
def _map_status(status: TaskStatus, progress: int = 0) -> str:
    """Map internal TaskStatus to MinerU official state string."""
    mapping = {
        TaskStatus.PENDING: "pending",
        TaskStatus.PROCESSING: "running" if progress > 0 else "pending",
        TaskStatus.SUCCESS: "done",
        TaskStatus.FAILED: "failed",
        TaskStatus.CANCELLED: "failed",
    }
    return mapping.get(status, "pending")


def _build_extract_result(task: ParseTask) -> ExtractTaskResultData:
    """Build ExtractTaskResultData from a ParseTask."""
    state = _map_status(task.status, task.progress)
    full_zip_url = None
    extract_progress = None

    if state == "done" and task.output_s3_prefix:
        # Generate a zip download URL — find the zip file in output
        objects = storage_service.list_objects(task.output_s3_prefix)
        for obj in objects:
            if obj["key"].endswith(".zip"):
                full_zip_url = storage_service.generate_download_presigned_url(
                    obj["key"], filename=obj["key"].split("/")[-1]
                )
                break
        # If no zip, provide a folder-level download link
        if not full_zip_url and objects:
            full_zip_url = storage_service.generate_download_presigned_url(
                objects[0]["key"], filename=objects[0]["key"].split("/")[-1]
            )

    if state == "running":
        extract_progress = ExtractProgress(
            extracted_pages=max(0, task.progress - 30),  # rough estimate
            total_pages=0,
            start_time=task.started_at.strftime("%Y-%m-%d %H:%M:%S") if task.started_at else None,
        )

    return ExtractTaskResultData(
        task_id=task.id,
        data_id=None,  # we don't store data_id yet
        state=state,
        full_zip_url=full_zip_url,
        err_msg=task.error_message or "",
        extract_progress=extract_progress,
    )


def _trace_id() -> str:
    return uuid.uuid4().hex


def _dispatch_celery_task(task: ParseTask, config: dict):
    """Dispatch a Celery parse task to the appropriate queue."""
    return dispatch_parse_task(task.id, task.input_s3_key, task.output_s3_prefix, config)


async def _download_url_to_s3(url: str, user_id: str) -> tuple[str, str, int]:
    """Download a file from URL and upload to S3. Returns (s3_key, filename, size)."""
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    # Extract filename from URL
    filename = url.rsplit("/", 1)[-1].split("?")[0] if "/" in url else "document.pdf"
    if "." not in filename:
        # Try content-disposition
        cd = resp.headers.get("content-disposition", "")
        if "filename=" in cd:
            filename = cd.split("filename=")[-1].strip('"').strip("'")
        else:
            ct = resp.headers.get("content-type", "")
            ext = "pdf" if "pdf" in ct else "bin"
            filename = f"{filename}.{ext}"

    data = resp.content
    size = len(data)
    s3_key = f"uploads/{user_id}/{uuid.uuid4()}/{filename}"
    content_type = resp.headers.get("content-type", "application/octet-stream")
    storage_service.upload_bytes(s3_key, data, content_type)

    return s3_key, filename, size


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/v4/extract/task — Single file parse by URL
# ═══════════════════════════════════════════════════════════════════════════
@router.post("/extract/task")
async def extract_task(
    payload: ExtractTaskRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a parse task from a file URL (MinerU official API compatible)."""
    try:
        s3_key, filename, size = await _download_url_to_s3(payload.url, current_user.id)
    except Exception as e:
        logger.error("Failed to download file from URL", url=payload.url, error=str(e))
        return {"code": -60008, "msg": "Failed to download file from URL", "trace_id": _trace_id(), "data": None}

    # Map model_version → backend
    backend = payload.model_version
    if backend == "vlm":
        backend = "vlm-transformers"

    # Map extra_formats → output_format
    output_format = "markdown"
    if payload.extra_formats:
        output_format = payload.extra_formats[0]  # primary extra format

    task = ParseTask(
        original_filename=filename,
        file_size_bytes=size,
        input_s3_key=s3_key,
        output_s3_prefix=f"results/{current_user.id}/{uuid.uuid4()}",
        backend=backend,
        output_format=output_format,
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

    config = {
        "backend": backend,
        "output_format": output_format,
        "language": payload.language or "ch",
        "is_ocr": payload.is_ocr,
        "enable_formula": payload.enable_formula,
        "enable_table": payload.enable_table,
        "page_ranges": payload.page_ranges,
        "extra_formats": payload.extra_formats,
    }
    celery_id = _dispatch_celery_task(task, config)
    task.celery_task_id = celery_id
    await db.commit()

    return {
        "code": 0,
        "msg": "ok",
        "trace_id": _trace_id(),
        "data": {"task_id": task.id},
    }


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/v4/extract/task/{task_id} — Get task result
# ═══════════════════════════════════════════════════════════════════════════
@router.get("/extract/task/{task_id}")
async def get_extract_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get parse task result (MinerU official API compatible)."""
    task = await db.get(ParseTask, task_id)
    if not task or task.user_id != current_user.id:
        return {"code": -60012, "msg": "Task not found", "trace_id": _trace_id(), "data": None}

    result = _build_extract_result(task)
    return {
        "code": 0,
        "msg": "ok",
        "trace_id": _trace_id(),
        "data": result.model_dump(exclude_none=True),
    }


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/v4/file-urls/batch — Batch presigned upload URLs
# ═══════════════════════════════════════════════════════════════════════════
@router.post("/file-urls/batch")
async def batch_file_urls(
    payload: BatchFileUrlsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get presigned upload URLs for batch file upload (≤50 files)."""
    if len(payload.files) > 50:
        return {"code": -500, "msg": "Maximum 50 files per batch", "trace_id": _trace_id(), "data": None}

    batch_id = str(uuid.uuid4())
    backend = payload.model_version
    if backend == "vlm":
        backend = "vlm-transformers"

    file_urls = []
    for f in payload.files:
        ext = f.name.rsplit(".", 1)[-1].lower() if "." in f.name else ""
        if ext not in settings.ALLOWED_EXTENSIONS:
            return {"code": -60002, "msg": f"File format not supported: {f.name}", "trace_id": _trace_id(), "data": None}

        s3_key = f"uploads/{current_user.id}/{uuid.uuid4()}/{f.name}"
        url = storage_service.generate_upload_presigned_url(s3_key, "application/octet-stream")
        file_urls.append(url)

        # Create task in DB immediately (pending until file is uploaded)
        output_format = "markdown"
        if payload.extra_formats:
            output_format = payload.extra_formats[0]

        task = ParseTask(
            original_filename=f.name,
            file_size_bytes=0,
            input_s3_key=s3_key,
            output_s3_prefix=f"results/{current_user.id}/{uuid.uuid4()}",
            backend=backend,
            output_format=output_format,
            language=payload.language or "ch",
            is_ocr=f.is_ocr if f.is_ocr is not None else False,
            enable_formula=payload.enable_formula,
            enable_table=payload.enable_table,
            page_ranges=f.page_ranges,
            user_id=current_user.id,
            organization_id=current_user.organization_id,
        )
        db.add(task)

    await db.commit()

    # Dispatch Celery tasks for all created tasks
    tasks_q = await db.execute(
        select(ParseTask).where(ParseTask.user_id == current_user.id).order_by(ParseTask.created_at.desc()).limit(len(payload.files))
    )
    for task in tasks_q.scalars().all():
        if task.celery_task_id:
            continue
        config = {
            "backend": backend,
            "output_format": task.output_format,
            "language": task.language,
            "is_ocr": task.is_ocr,
            "enable_formula": task.enable_formula,
            "enable_table": task.enable_table,
            "page_ranges": task.page_ranges,
            "extra_formats": payload.extra_formats,
        }
        celery_id = _dispatch_celery_task(task, config)
        task.celery_task_id = celery_id
    await db.commit()

    return {
        "code": 0,
        "msg": "ok",
        "trace_id": _trace_id(),
        "data": {
            "batch_id": batch_id,
            "file_urls": file_urls,
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/v4/extract/task/batch — Batch URL parse
# ═══════════════════════════════════════════════════════════════════════════
@router.post("/extract/task/batch")
async def batch_url_extract(
    payload: BatchUrlExtractRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Batch parse files by URLs (≤50 files)."""
    if len(payload.files) > 50:
        return {"code": -500, "msg": "Maximum 50 files per batch", "trace_id": _trace_id(), "data": None}

    batch_id = str(uuid.uuid4())
    backend = payload.model_version
    if backend == "vlm":
        backend = "vlm-transformers"

    for f in payload.files:
        try:
            s3_key, filename, size = await _download_url_to_s3(f.url, current_user.id)
        except Exception as e:
            logger.error("Batch: failed to download URL", url=f.url, error=str(e))
            continue

        output_format = "markdown"
        if payload.extra_formats:
            output_format = payload.extra_formats[0]

        task = ParseTask(
            original_filename=filename,
            file_size_bytes=size,
            input_s3_key=s3_key,
            output_s3_prefix=f"results/{current_user.id}/{uuid.uuid4()}",
            backend=backend,
            output_format=output_format,
            language=payload.language or "ch",
            is_ocr=f.is_ocr if f.is_ocr is not None else False,
            enable_formula=payload.enable_formula,
            enable_table=payload.enable_table,
            page_ranges=f.page_ranges,
            user_id=current_user.id,
            organization_id=current_user.organization_id,
        )
        db.add(task)

    await db.commit()

    # Dispatch Celery for recently created tasks
    tasks_q = await db.execute(
        select(ParseTask).where(ParseTask.user_id == current_user.id).order_by(ParseTask.created_at.desc()).limit(len(payload.files))
    )
    for task in tasks_q.scalars().all():
        if task.celery_task_id:
            continue
        config = {
            "backend": backend,
            "output_format": task.output_format,
            "language": task.language,
            "is_ocr": task.is_ocr,
            "enable_formula": task.enable_formula,
            "enable_table": task.enable_table,
            "page_ranges": task.page_ranges,
            "extra_formats": payload.extra_formats,
        }
        celery_id = _dispatch_celery_task(task, config)
        task.celery_task_id = celery_id
    await db.commit()

    return {
        "code": 0,
        "msg": "ok",
        "trace_id": _trace_id(),
        "data": {"batch_id": batch_id},
    }


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/v4/extract-results/batch/{batch_id} — Batch results
# ═══════════════════════════════════════════════════════════════════════════
@router.get("/extract-results/batch/{batch_id}")
async def batch_extract_results(
    batch_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get batch parse results. Returns all recent tasks for the user."""
    # We don't store batch_id in the DB yet — return recent tasks
    tasks_q = await db.execute(
        select(ParseTask)
        .where(ParseTask.user_id == current_user.id)
        .order_by(ParseTask.created_at.desc())
        .limit(50)
    )
    tasks = tasks_q.scalars().all()

    results = []
    for task in tasks:
        result = _build_extract_result(task)
        results.append(BatchExtractResultItem(
            file_name=task.original_filename,
            state=result.state,
            full_zip_url=result.full_zip_url,
            err_msg=result.err_msg,
            data_id=None,
            extract_progress=result.extract_progress,
        ))

    return {
        "code": 0,
        "msg": "ok",
        "trace_id": _trace_id(),
        "data": {
            "batch_id": batch_id,
            "extract_result": [r.model_dump(exclude_none=True) for r in results],
        },
    }
