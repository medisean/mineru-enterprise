"""
MinerU Official API Compatible Endpoints — Agent Lightweight Parse API (v1).
Matches the official API at https://mineru.net/apiManage/docs

No authentication required. IP rate-limited.

Endpoints:
  POST /api/v1/agent/parse/url          — Parse by URL (lightweight)
  POST /api/v1/agent/parse/file         — Parse by file upload (presigned URL)
  GET  /api/v1/agent/parse/{task_id}    — Get parse result
"""
import uuid
import time
import mimetypes
from pathlib import Path
import structlog
from typing import Optional

import httpx
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.config import settings
from app.models.models import ParseTask, TaskStatus
from app.schemas.schemas import (
    AgentUrlParseRequest, AgentFileParseRequest,
    AgentParseResultData,
)
from app.services.storage import storage_service
from app.workers.parse_worker import dispatch_parse_task
from app.services.file_validation import validate_file_magic

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/agent", tags=["MinerU Agent API"])

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

# Simple in-memory rate limiter (per-IP)
_rate_limit_store: dict[str, list[float]] = {}
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX = 30     # requests per window


def _check_rate_limit(client_ip: str) -> bool:
    """Return True if request is allowed, False if rate-limited."""
    now = time.time()
    if client_ip not in _rate_limit_store:
        _rate_limit_store[client_ip] = []

    # Clean old entries
    _rate_limit_store[client_ip] = [t for t in _rate_limit_store[client_ip] if now - t < RATE_LIMIT_WINDOW]

    if len(_rate_limit_store[client_ip]) >= RATE_LIMIT_MAX:
        return False

    _rate_limit_store[client_ip].append(now)
    return True


def _trace_id() -> str:
    return uuid.uuid4().hex


def _map_agent_status(status: TaskStatus, progress: int = 0) -> str:
    """Map internal TaskStatus to Agent API state string."""
    mapping = {
        TaskStatus.PENDING: "pending",
        TaskStatus.PROCESSING: "running" if progress > 0 else "pending",
        TaskStatus.SUCCESS: "done",
        TaskStatus.FAILED: "failed",
        TaskStatus.CANCELLED: "failed",
    }
    return mapping.get(status, "pending")


async def _get_or_create_system_user(db: AsyncSession) -> str:
    """Get or create a system user for Agent API tasks (no auth required)."""
    from app.models.models import User
    result = await db.execute(select(User).where(User.username == "agent_system"))
    user = result.scalar_one_or_none()
    if user:
        return user.id

    # Create system user
    from app.core.security import hash_password
    user = User(
        email="agent@system.local",
        username="agent_system",
        hashed_password=hash_password(uuid.uuid4().hex),
        full_name="Agent API System",
        role="member",
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user.id


async def _download_url_to_s3(url: str, user_id: str) -> tuple[str, str, int]:
    """Download a file from URL and upload to S3. Returns (s3_key, filename, size)."""
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    filename = url.rsplit("/", 1)[-1].split("?")[0] if "/" in url else "document.pdf"
    if "." not in filename:
        ct = resp.headers.get("content-type", "")
        ext = "pdf" if "pdf" in ct else "bin"
        filename = f"{filename}.{ext}"

    data = resp.content
    content_type = resp.headers.get("content-type", "")
    ext = Path(filename).suffix.lstrip(".").lower()
    if ext not in settings.ALLOWED_EXTENSIONS:
        mime = content_type.split(";", 1)[0].strip().lower()
        ext = CONTENT_TYPE_TO_EXTENSION.get(mime) or ""
        if not ext and mime:
            guessed = mimetypes.guess_extension(mime)
            ext = guessed.lstrip(".").lower() if guessed else ""
        if not ext:
            if data.startswith(b"%PDF"):
                ext = "pdf"
            elif data.startswith(b"\x89PNG"):
                ext = "png"
            elif data.startswith(b"\xff\xd8\xff"):
                ext = "jpg"
            elif data.startswith(b"GIF8"):
                ext = "gif"
            elif data.startswith(b"BM"):
                ext = "bmp"
            elif data.startswith(b"\x00\x00\x00\x0cjP  \r\n\x87\n") or data.startswith(b"\xffO\xffQ"):
                ext = "jp2"
            elif data.startswith(b"II*\x00") or data.startswith(b"MM\x00*"):
                ext = "tiff"
            elif data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
                ext = "webp"
        if ext not in settings.ALLOWED_EXTENSIONS:
            raise UnsupportedDownloadedFileType(f"Unsupported file type from URL: {filename}")

        current_ext = Path(filename).suffix.lstrip(".").lower()
        if current_ext != ext:
            filename = f"{Path(filename).stem or 'document'}.{ext}"

    if not validate_file_magic(data[:32], ext):
        raise UnsupportedDownloadedFileType(f"File content does not match the '.{ext}' format: {filename}")

    size = len(data)
    s3_key = f"uploads/{user_id}/{uuid.uuid4()}/{filename}"
    storage_service.upload_bytes(
        s3_key,
        data,
        CONTENT_TYPE_BY_EXTENSION.get(ext, content_type or "application/octet-stream"),
    )

    return s3_key, filename, size


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/v1/agent/parse/url — Lightweight URL parse
# ═══════════════════════════════════════════════════════════════════════════
@router.post("/parse/url")
async def agent_parse_url(
    payload: AgentUrlParseRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Lightweight parse — submit URL, no auth required, IP rate-limited."""
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip):
        return {"code": -30004, "msg": "Rate limit exceeded, please slow down", "trace_id": _trace_id(), "data": None}

    user_id = await _get_or_create_system_user(db)

    try:
        s3_key, filename, size = await _download_url_to_s3(payload.url, user_id)
    except UnsupportedDownloadedFileType as e:
        logger.warning("Agent: unsupported file from URL", url=payload.url, error=str(e))
        return {"code": -30002, "msg": str(e), "trace_id": _trace_id(), "data": None}
    except Exception as e:
        logger.error("Agent: failed to download URL", url=payload.url, error=str(e))
        return {"code": -60008, "msg": "Failed to download file from URL", "trace_id": _trace_id(), "data": None}

    # Agent API only outputs markdown
    task = ParseTask(
        original_filename=filename,
        file_size_bytes=size,
        input_s3_key=s3_key,
        output_s3_prefix=f"results/{user_id}/{uuid.uuid4()}",
        backend="pipeline",
        output_format="markdown",
        language=payload.language or "ch",
        is_ocr=payload.is_ocr,
        enable_formula=payload.enable_formula,
        enable_table=payload.enable_table,
        page_ranges=payload.page_range,  # Agent uses "page_range" (singular)
        user_id=user_id,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    config = {
        "backend": "pipeline",
        "output_format": "markdown",
        "language": payload.language or "ch",
        "is_ocr": payload.is_ocr,
        "enable_formula": payload.enable_formula,
        "enable_table": payload.enable_table,
        "page_ranges": payload.page_range,
    }
    celery_task_id = dispatch_parse_task(task.id, task.input_s3_key, task.output_s3_prefix, config)
    task.celery_task_id = celery_task_id
    await db.commit()

    return {
        "code": 0,
        "msg": "ok",
        "trace_id": _trace_id(),
        "data": {"task_id": task.id},
    }


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/v1/agent/parse/file — Lightweight file upload parse
# ═══════════════════════════════════════════════════════════════════════════
@router.post("/parse/file")
async def agent_parse_file(
    payload: AgentFileParseRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Lightweight parse — get presigned upload URL, no auth required."""
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip):
        return {"code": -30004, "msg": "Rate limit exceeded, please slow down", "trace_id": _trace_id(), "data": None}

    ext = payload.file_name.rsplit(".", 1)[-1].lower() if "." in payload.file_name else ""
    if ext not in settings.ALLOWED_EXTENSIONS:
        return {"code": -30002, "msg": f"Unsupported file type: .{ext}", "trace_id": _trace_id(), "data": None}

    user_id = await _get_or_create_system_user(db)

    s3_key = f"uploads/{user_id}/{uuid.uuid4()}/{payload.file_name}"
    file_url = storage_service.generate_upload_presigned_url(s3_key, "application/octet-stream")

    # Create task in DB
    task = ParseTask(
        original_filename=payload.file_name,
        file_size_bytes=0,
        input_s3_key=s3_key,
        output_s3_prefix=f"results/{user_id}/{uuid.uuid4()}",
        backend="pipeline",
        output_format="markdown",
        language=payload.language or "ch",
        is_ocr=payload.is_ocr,
        enable_formula=payload.enable_formula,
        enable_table=payload.enable_table,
        page_ranges=payload.page_range,
        user_id=user_id,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    # Auto-dispatch Celery task (file may not be uploaded yet, but worker will retry)
    config = {
        "backend": "pipeline",
        "output_format": "markdown",
        "language": payload.language or "ch",
        "is_ocr": payload.is_ocr,
        "enable_formula": payload.enable_formula,
        "enable_table": payload.enable_table,
        "page_ranges": payload.page_range,
    }
    celery_task_id = dispatch_parse_task(task.id, task.input_s3_key, task.output_s3_prefix, config)
    task.celery_task_id = celery_task_id
    await db.commit()

    return {
        "code": 0,
        "msg": "ok",
        "trace_id": _trace_id(),
        "data": {
            "task_id": task.id,
            "file_url": file_url,
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/v1/agent/parse/{task_id} — Get parse result
# ═══════════════════════════════════════════════════════════════════════════
@router.get("/parse/{task_id}")
async def agent_parse_result(
    task_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get lightweight parse result — no auth required."""
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip):
        return {"code": -30004, "msg": "Rate limit exceeded", "trace_id": _trace_id(), "data": None}

    task = await db.get(ParseTask, task_id)
    if not task:
        return {"code": -60012, "msg": "Task not found", "trace_id": _trace_id(), "data": None}

    state = _map_agent_status(task.status, task.progress)
    markdown_url = None
    err_code = None

    if state == "done" and task.output_s3_prefix:
        objects = storage_service.list_objects(task.output_s3_prefix)
        for obj in objects:
            if obj["key"].endswith(".md"):
                markdown_url = storage_service.generate_download_presigned_url(obj["key"])
                break
        if not markdown_url and objects:
            # Fallback: return first file
            markdown_url = storage_service.generate_download_presigned_url(objects[0]["key"])

    if state == "failed":
        err_code = -60010  # generic parse failure

    result_data = {
        "task_id": task.id,
        "state": state,
        "markdown_url": markdown_url,
        "err_msg": task.error_message or "",
        "err_code": err_code,
    }

    return {
        "code": 0,
        "msg": "ok",
        "trace_id": _trace_id(),
        "data": {k: v for k, v in result_data.items() if v is not None},
    }
