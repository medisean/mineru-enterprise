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
import mimetypes
import structlog
from datetime import datetime, timezone
from pathlib import Path
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
from app.services.file_validation import validate_file_magic
from app.services.official_result_exports import ensure_full_result_zip, normalize_extra_formats
from app.services.storage import storage_service
from app.workers.parse_worker import dispatch_parse_task

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v4", tags=["MinerU Precision API"])
MAX_BATCH_FILES = 200

CONTENT_TYPE_TO_EXTENSION = {
    "application/pdf": "pdf",
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/jp2": "jp2",
    "image/jpeg2000": "jp2",
    "image/gif": "gif",
    "image/bmp": "bmp",
    "image/webp": "webp",
    "image/tiff": "tiff",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
}
CONTENT_TYPE_BY_EXTENSION = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
    "jp2": "image/jp2",
    "webp": "image/webp",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "tiff": "image/tiff",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


class UnsupportedDownloadedFileType(ValueError):
    pass


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
        zip_key = ensure_full_result_zip(storage_service, task.output_s3_prefix)
        if zip_key:
            full_zip_url = storage_service.generate_download_presigned_url(
                zip_key,
                filename=f"{Path(task.original_filename).stem or task.id}.zip",
            )

    if state == "running":
        extract_progress = ExtractProgress(
            extracted_pages=max(0, task.progress - 30),  # rough estimate
            total_pages=0,
            start_time=task.started_at.strftime("%Y-%m-%d %H:%M:%S") if task.started_at else None,
        )

    return ExtractTaskResultData(
        task_id=task.id,
        data_id=task.data_id,
        state=state,
        full_zip_url=full_zip_url,
        err_msg=task.error_message or "",
        extract_progress=extract_progress,
    )


def _trace_id() -> str:
    return uuid.uuid4().hex


def _map_model_version(model_version: str | None) -> str:
    backend = (model_version or "").strip()
    if backend == "vlm":
        return "vlm-auto-engine"
    if backend == "hybrid":
        return "hybrid-auto-engine"
    return backend


def _output_format_from_extra_formats(extra_formats: list[str] | None) -> str:
    formats = normalize_extra_formats(extra_formats)
    return ",".join(["markdown", *formats]) if formats else "markdown"


def _dispatch_celery_task(task: ParseTask, config: dict):
    """Dispatch a Celery parse task to the appropriate queue."""
    return dispatch_parse_task(task.id, task.input_s3_key, task.output_s3_prefix, config)


def _infer_supported_extension(filename: str, content_type: str, data: bytes) -> str:
    ext = Path(filename).suffix.lstrip(".").lower()
    if ext in settings.ALLOWED_EXTENSIONS:
        return ext

    mime = content_type.split(";", 1)[0].strip().lower()
    inferred = CONTENT_TYPE_TO_EXTENSION.get(mime)
    if not inferred and mime:
        guessed = mimetypes.guess_extension(mime)
        inferred = guessed.lstrip(".").lower() if guessed else ""
    if inferred in settings.ALLOWED_EXTENSIONS:
        return inferred

    if data.startswith(b"%PDF"):
        return "pdf"
    if data.startswith(b"\x89PNG"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"GIF8"):
        return "gif"
    if data.startswith(b"BM"):
        return "bmp"
    if data.startswith(b"\x00\x00\x00\x0cjP  \r\n\x87\n") or data.startswith(b"\xffO\xffQ"):
        return "jp2"
    if data.startswith(b"II*\x00") or data.startswith(b"MM\x00*"):
        return "tiff"
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        return "webp"
    return ""


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
    content_type = resp.headers.get("content-type", "")
    ext = _infer_supported_extension(filename, content_type, data)
    if not ext:
        raise UnsupportedDownloadedFileType(f"File format not supported: {filename}")
    if not validate_file_magic(data[:32], ext):
        raise UnsupportedDownloadedFileType(f"File content does not match the '.{ext}' format: {filename}")

    current_ext = Path(filename).suffix.lstrip(".").lower()
    if current_ext != ext:
        filename = f"{Path(filename).stem or 'document'}.{ext}"

    size = len(data)
    s3_key = f"uploads/{user_id}/{uuid.uuid4()}/{filename}"
    storage_service.upload_bytes(
        s3_key,
        data,
        CONTENT_TYPE_BY_EXTENSION.get(ext, content_type or "application/octet-stream"),
    )

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
    except UnsupportedDownloadedFileType as e:
        logger.warning("Unsupported file from URL", url=payload.url, error=str(e))
        return {"code": -60002, "msg": str(e), "trace_id": _trace_id(), "data": None}
    except Exception as e:
        logger.error("Failed to download file from URL", url=payload.url, error=str(e))
        return {"code": -60008, "msg": "Failed to download file from URL", "trace_id": _trace_id(), "data": None}

    backend = _map_model_version(payload.model_version)
    output_format = _output_format_from_extra_formats(payload.extra_formats)

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
        data_id=payload.data_id,
        callback_url=payload.callback,
        callback_seed=payload.seed,
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
        "extra_formats": normalize_extra_formats(payload.extra_formats),
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
    """Get presigned upload URLs for batch file upload (≤200 files)."""
    if len(payload.files) > MAX_BATCH_FILES:
        return {"code": -500, "msg": f"Maximum {MAX_BATCH_FILES} files per batch", "trace_id": _trace_id(), "data": None}

    batch_id = str(uuid.uuid4())
    backend = _map_model_version(payload.model_version)
    output_format = _output_format_from_extra_formats(payload.extra_formats)
    created_tasks = []

    file_urls = []
    for f in payload.files:
        ext = f.name.rsplit(".", 1)[-1].lower() if "." in f.name else ""
        if ext not in settings.ALLOWED_EXTENSIONS:
            return {"code": -60002, "msg": f"File format not supported: {f.name}", "trace_id": _trace_id(), "data": None}

        s3_key = f"uploads/{current_user.id}/{uuid.uuid4()}/{f.name}"
        url = storage_service.generate_upload_presigned_url(s3_key, "application/octet-stream")
        file_urls.append(url)

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
            data_id=f.data_id,
            callback_url=payload.callback,
            callback_seed=payload.seed,
            batch_id=batch_id,
            user_id=current_user.id,
            organization_id=current_user.organization_id,
        )
        db.add(task)
        created_tasks.append(task)

    await db.commit()

    for task in created_tasks:
        await db.refresh(task)
        config = {
            "backend": backend,
            "output_format": task.output_format,
            "language": task.language,
            "is_ocr": task.is_ocr,
            "enable_formula": task.enable_formula,
            "enable_table": task.enable_table,
            "page_ranges": task.page_ranges,
            "extra_formats": normalize_extra_formats(payload.extra_formats),
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
    if len(payload.files) > MAX_BATCH_FILES:
        return {"code": -500, "msg": f"Maximum {MAX_BATCH_FILES} files per batch", "trace_id": _trace_id(), "data": None}

    batch_id = str(uuid.uuid4())
    backend = _map_model_version(payload.model_version)
    output_format = _output_format_from_extra_formats(payload.extra_formats)
    created_tasks = []

    for f in payload.files:
        try:
            s3_key, filename, size = await _download_url_to_s3(f.url, current_user.id)
        except UnsupportedDownloadedFileType as e:
            logger.warning("Batch: unsupported URL file", url=f.url, error=str(e))
            continue
        except Exception as e:
            logger.error("Batch: failed to download URL", url=f.url, error=str(e))
            continue

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
            data_id=f.data_id,
            callback_url=payload.callback,
            callback_seed=payload.seed,
            batch_id=batch_id,
            user_id=current_user.id,
            organization_id=current_user.organization_id,
        )
        db.add(task)
        created_tasks.append(task)

    await db.commit()

    for task in created_tasks:
        await db.refresh(task)
        config = {
            "backend": backend,
            "output_format": task.output_format,
            "language": task.language,
            "is_ocr": task.is_ocr,
            "enable_formula": task.enable_formula,
            "enable_table": task.enable_table,
            "page_ranges": task.page_ranges,
            "extra_formats": normalize_extra_formats(payload.extra_formats),
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
    """Get batch parse results by batch_id."""
    tasks_q = await db.execute(
        select(ParseTask)
        .where(ParseTask.user_id == current_user.id, ParseTask.batch_id == batch_id)
        .order_by(ParseTask.created_at.asc())
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
            data_id=task.data_id,
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
