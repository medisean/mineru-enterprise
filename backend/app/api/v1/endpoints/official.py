"""
MinerU official API compatible endpoints.

Implements the core MinerU FastAPI surface:
  POST /tasks
  GET  /tasks/{task_id}
  GET  /tasks/{task_id}/result
  POST /file_parse

The implementation uses this platform's S3 + Celery task pipeline rather than
MinerU's in-process task manager.
"""
import asyncio
import base64
import mimetypes
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import hash_password
from app.models.models import ParseTask, TaskStatus, User
from app.services.file_validation import validate_file_magic
from app.services.official_result_exports import build_result_zip_bytes
from app.services.storage import storage_service
from app.workers.parse_worker import dispatch_parse_task

router = APIRouter(tags=["MinerU Official API"])

SUPPORTED_EXTENSIONS = {
    "pdf",
    "png", "jpeg", "jp2", "webp", "gif", "bmp", "jpg", "tiff",
    "docx", "pptx", "xlsx",
}
IMAGE_EXTENSIONS = {"png", "jpeg", "jp2", "webp", "gif", "bmp", "jpg", "tiff"}
TASK_PENDING = "pending"
TASK_PROCESSING = "processing"
TASK_COMPLETED = "completed"
TASK_FAILED = "failed"
CONTENT_TYPE_BY_EXTENSION = {
    "jp2": "image/jp2",
    "tiff": "image/tiff",
}


async def _get_or_create_official_user(db: AsyncSession) -> User:
    result = await db.execute(select(User).where(User.username == "official_api_system"))
    user = result.scalar_one_or_none()
    if user:
        return user

    user = User(
        email="official-api@system.local",
        username="official_api_system",
        hashed_password=hash_password(uuid.uuid4().hex),
        full_name="Official API System",
        role="member",
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


def _ext(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _task_status(task: ParseTask) -> str:
    if task.status == TaskStatus.SUCCESS:
        return TASK_COMPLETED
    if task.status == TaskStatus.FAILED:
        return TASK_FAILED
    if task.status == TaskStatus.CANCELLED:
        return TASK_FAILED
    if task.status == TaskStatus.PROCESSING:
        return TASK_PROCESSING
    return TASK_PENDING


def _parse_page_range(start_page_id: int, end_page_id: int) -> Optional[str]:
    if start_page_id <= 0 and end_page_id >= 99999:
        return None
    start = max(start_page_id, 0) + 1
    end = max(end_page_id, start_page_id) + 1
    return f"{start}-{end}"


def _parse_method_to_ocr(parse_method: str) -> Optional[bool]:
    if parse_method == "ocr":
        return True
    if parse_method == "txt":
        return False
    return None


def _result_urls(task: ParseTask, request: Request) -> tuple[str, str]:
    return (
        str(request.url_for("official_get_task_status", task_id=task.id)),
        str(request.url_for("official_get_task_result", task_id=task.id)),
    )


def _status_payload(task: ParseTask, request: Request) -> dict:
    status_url, result_url = _result_urls(task, request)
    return {
        "task_id": task.id,
        "status": _task_status(task),
        "backend": task.backend or settings.MINERU_BACKEND or "hybrid-auto-engine",
        "file_names": [Path(task.original_filename).stem],
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "error": task.error_message,
        "status_url": status_url,
        "result_url": result_url,
        "queued_ahead": 0,
    }


def _content_type_for(filename: str) -> str:
    ext = _ext(filename)
    return mimetypes.guess_type(filename)[0] or CONTENT_TYPE_BY_EXTENSION.get(ext) or "application/octet-stream"


def _download_timestamp(task: ParseTask) -> str:
    dt = task.completed_at or task.created_at or datetime.now(timezone.utc)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y%m%d%H%M%S")


def _download_filename(task: ParseTask, extension: str) -> str:
    stem = Path(task.original_filename).stem or task.id
    return f"{stem}_{_download_timestamp(task)}.{extension.lstrip('.')}"


async def _save_upload_as_task(
    upload: UploadFile,
    user: User,
    db: AsyncSession,
    *,
    backend: str,
    parse_method: str,
    lang: str,
    formula_enable: bool,
    table_enable: bool,
    image_analysis: bool,
    start_page_id: int,
    end_page_id: int,
    return_md: bool,
    return_middle_json: bool,
    return_model_output: bool,
    return_content_list: bool,
    return_images: bool,
) -> ParseTask:
    filename = upload.filename or f"upload-{uuid.uuid4()}.pdf"
    ext = _ext(filename)
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: .{ext}")

    content = await upload.read()
    await upload.close()
    if len(content) > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"File too large (max {settings.MAX_UPLOAD_SIZE_MB} MB)")
    if not validate_file_magic(content[:32], ext):
        raise HTTPException(status_code=400, detail=f"File content does not match the '.{ext}' extension")

    s3_key = f"uploads/{user.id}/{uuid.uuid4()}/{filename}"
    storage_service.upload_bytes(s3_key, content, _content_type_for(filename))

    wants_json = return_middle_json or return_model_output or return_content_list
    output_format = "both" if return_md and wants_json else ("json" if wants_json and not return_md else "markdown")
    task = ParseTask(
        original_filename=filename,
        file_size_bytes=len(content),
        input_s3_key=s3_key,
        output_s3_prefix=f"results/{user.id}/{uuid.uuid4()}",
        backend=backend,
        output_format=output_format,
        language=lang,
        is_ocr=_parse_method_to_ocr(parse_method),
        enable_formula=formula_enable,
        enable_table=table_enable,
        page_ranges=_parse_page_range(start_page_id, end_page_id),
        user_id=user.id,
        organization_id=user.organization_id,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    celery_task_id = dispatch_parse_task(task.id, task.input_s3_key, task.output_s3_prefix, {
        "backend": backend,
        "output_format": output_format,
        "language": lang,
        "is_ocr": _parse_method_to_ocr(parse_method),
        "enable_formula": formula_enable,
        "enable_table": table_enable,
        "image_analysis": image_analysis,
        "page_ranges": task.page_ranges,
        "return_md": return_md,
        "return_middle_json": return_middle_json,
        "return_model_output": return_model_output,
        "return_content_list": return_content_list,
        "return_images": return_images,
    })
    task.celery_task_id = celery_task_id
    await db.commit()
    await db.refresh(task)
    return task


def _find_result_key(objects: list[dict], suffixes: tuple[str, ...], stem: str) -> Optional[str]:
    stem_matches = []
    suffix_matches = []
    for obj in objects:
        key = obj["key"]
        filename = key.rsplit("/", 1)[-1]
        if filename.endswith(suffixes):
            suffix_matches.append(key)
            if filename.startswith(stem):
                stem_matches.append(key)
    return stem_matches[0] if stem_matches else (suffix_matches[0] if suffix_matches else None)


def _download_text(key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    return storage_service.download_bytes(key).decode("utf-8", errors="replace")


def _download_json_text(key: Optional[str]) -> Optional[str]:
    return _download_text(key)


def _build_results(task: ParseTask, *, return_md: bool, return_middle_json: bool, return_model_output: bool, return_content_list: bool, return_images: bool) -> dict:
    objects = storage_service.list_objects(task.output_s3_prefix or "")
    stem = Path(task.original_filename).stem
    data: dict = {}

    if return_md:
        data["md_content"] = _download_text(_find_result_key(objects, (".md",), stem))
    if return_middle_json:
        data["middle_json"] = _download_json_text(_find_result_key(objects, ("_middle.json", "middle.json"), stem))
    if return_model_output:
        data["model_output"] = _download_json_text(_find_result_key(objects, ("_model.json", "model.json"), stem))
    if return_content_list:
        data["content_list"] = _download_json_text(_find_result_key(objects, ("_content_list.json", "content_list.json"), stem))
    if return_images:
        images: dict[str, str] = {}
        for obj in objects:
            key = obj["key"]
            ext = _ext(key)
            if "/images/" in key and ext in IMAGE_EXTENSIONS:
                raw = storage_service.download_bytes(key)
                filename = key.rsplit("/", 1)[-1]
                mime = _content_type_for(filename)
                images[filename] = f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
        data["images"] = images

    return {stem: data}


def _build_zip(task: ParseTask, *, return_original_file: bool) -> bytes:
    return build_result_zip_bytes(
        storage_service,
        task.output_s3_prefix or "",
        original_key=task.input_s3_key if return_original_file else None,
        original_filename=task.original_filename if return_original_file else None,
    )


async def _wait_for_task(task_id: str, db: AsyncSession, timeout_seconds: int = 3600) -> ParseTask:
    deadline = asyncio.get_event_loop().time() + timeout_seconds
    while True:
        task = await db.get(ParseTask, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        if task.status in (TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED):
            return task
        if asyncio.get_event_loop().time() >= deadline:
            return task
        await asyncio.sleep(2)


async def _submit_tasks(
    request: Request,
    files: list[UploadFile],
    db: AsyncSession,
    *,
    lang_list: list[str],
    backend: str,
    parse_method: str,
    formula_enable: bool,
    table_enable: bool,
    image_analysis: bool,
    return_md: bool,
    return_middle_json: bool,
    return_model_output: bool,
    return_content_list: bool,
    return_images: bool,
    start_page_id: int,
    end_page_id: int,
) -> list[ParseTask]:
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")
    user = await _get_or_create_official_user(db)
    lang = lang_list[0] if lang_list else "ch"
    tasks = []
    for upload in files:
        tasks.append(await _save_upload_as_task(
            upload,
            user,
            db,
            backend=backend,
            parse_method=parse_method,
            lang=lang,
            formula_enable=formula_enable,
            table_enable=table_enable,
            image_analysis=image_analysis,
            start_page_id=start_page_id,
            end_page_id=end_page_id,
            return_md=return_md,
            return_middle_json=return_middle_json,
            return_model_output=return_model_output,
            return_content_list=return_content_list,
            return_images=return_images,
        ))
    return tasks


@router.post("/tasks", status_code=202)
async def official_submit_task(
    request: Request,
    files: Annotated[list[UploadFile], File(description="Upload PDF, image, DOCX, PPTX, or XLSX files for parsing")],
    lang_list: Annotated[list[str], Form()] = ["ch"],
    backend: Annotated[str, Form()] = "hybrid-auto-engine",
    parse_method: Annotated[str, Form()] = "auto",
    formula_enable: Annotated[bool, Form()] = True,
    table_enable: Annotated[bool, Form()] = True,
    image_analysis: Annotated[bool, Form()] = False,
    server_url: Annotated[Optional[str], Form()] = None,
    return_md: Annotated[bool, Form()] = True,
    return_middle_json: Annotated[bool, Form()] = False,
    return_model_output: Annotated[bool, Form()] = False,
    return_content_list: Annotated[bool, Form()] = False,
    return_images: Annotated[bool, Form()] = False,
    response_format_zip: Annotated[bool, Form()] = False,
    return_original_file: Annotated[bool, Form()] = False,
    start_page_id: Annotated[int, Form()] = 0,
    end_page_id: Annotated[int, Form()] = 99999,
    db: AsyncSession = Depends(get_db),
):
    tasks = await _submit_tasks(
        request,
        files,
        db,
        lang_list=lang_list,
        backend=backend,
        parse_method=parse_method,
        formula_enable=formula_enable,
        table_enable=table_enable,
        image_analysis=image_analysis,
        return_md=return_md,
        return_middle_json=return_middle_json,
        return_model_output=return_model_output,
        return_content_list=return_content_list,
        return_images=return_images,
        start_page_id=start_page_id,
        end_page_id=end_page_id,
    )
    task = tasks[0]
    payload = _status_payload(task, request)
    payload["message"] = "Task submitted successfully"
    if len(tasks) > 1:
        payload["task_ids"] = [t.id for t in tasks]
    return JSONResponse(status_code=202, content=payload)


@router.get("/tasks/{task_id}", name="official_get_task_status")
async def official_get_task_status(task_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    task = await db.get(ParseTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return _status_payload(task, request)


@router.get("/tasks/{task_id}/result", name="official_get_task_result")
async def official_get_task_result(
    task_id: str,
    request: Request,
    return_md: bool = True,
    return_middle_json: bool = False,
    return_model_output: bool = False,
    return_content_list: bool = False,
    return_images: bool = False,
    response_format_zip: bool = False,
    return_original_file: bool = False,
    db: AsyncSession = Depends(get_db),
):
    task = await db.get(ParseTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status in (TaskStatus.PENDING, TaskStatus.PROCESSING):
        payload = _status_payload(task, request)
        payload["message"] = "Task result is not ready yet"
        return JSONResponse(status_code=202, content=payload)
    if task.status != TaskStatus.SUCCESS:
        payload = _status_payload(task, request)
        payload["message"] = "Task execution failed"
        return JSONResponse(status_code=409, content=payload)

    if response_format_zip:
        data = _build_zip(task, return_original_file=return_original_file)
        headers = {"Content-Disposition": f'attachment; filename="{_download_filename(task, "zip")}"'}
        return Response(content=data, media_type="application/zip", headers=headers)

    return {
        "backend": task.backend,
        "version": "compatible",
        "results": _build_results(
            task,
            return_md=return_md,
            return_middle_json=return_middle_json,
            return_model_output=return_model_output,
            return_content_list=return_content_list,
            return_images=return_images,
        ),
    }


@router.post("/file_parse")
async def official_file_parse(
    request: Request,
    files: Annotated[list[UploadFile], File(description="Upload PDF, image, DOCX, PPTX, or XLSX files for parsing")],
    lang_list: Annotated[list[str], Form()] = ["ch"],
    backend: Annotated[str, Form()] = "hybrid-auto-engine",
    parse_method: Annotated[str, Form()] = "auto",
    formula_enable: Annotated[bool, Form()] = True,
    table_enable: Annotated[bool, Form()] = True,
    image_analysis: Annotated[bool, Form()] = False,
    server_url: Annotated[Optional[str], Form()] = None,
    return_md: Annotated[bool, Form()] = True,
    return_middle_json: Annotated[bool, Form()] = False,
    return_model_output: Annotated[bool, Form()] = False,
    return_content_list: Annotated[bool, Form()] = False,
    return_images: Annotated[bool, Form()] = False,
    response_format_zip: Annotated[bool, Form()] = False,
    return_original_file: Annotated[bool, Form()] = False,
    start_page_id: Annotated[int, Form()] = 0,
    end_page_id: Annotated[int, Form()] = 99999,
    db: AsyncSession = Depends(get_db),
):
    tasks = await _submit_tasks(
        request,
        files,
        db,
        lang_list=lang_list,
        backend=backend,
        parse_method=parse_method,
        formula_enable=formula_enable,
        table_enable=table_enable,
        image_analysis=image_analysis,
        return_md=return_md,
        return_middle_json=return_middle_json,
        return_model_output=return_model_output,
        return_content_list=return_content_list,
        return_images=return_images,
        start_page_id=start_page_id,
        end_page_id=end_page_id,
    )
    task = await _wait_for_task(tasks[0].id, db)
    if task.status != TaskStatus.SUCCESS:
        payload = _status_payload(task, request)
        status_code = 409 if task.status in (TaskStatus.FAILED, TaskStatus.CANCELLED) else 202
        payload["message"] = "Task execution failed" if status_code == 409 else "Task result is not ready yet"
        return JSONResponse(status_code=status_code, content=payload)

    if response_format_zip:
        data = _build_zip(task, return_original_file=return_original_file and response_format_zip)
        headers = {
            "Content-Disposition": f'attachment; filename="{_download_filename(task, "zip")}"',
            "X-MinerU-Task-Id": task.id,
            "X-MinerU-Task-Status": _task_status(task),
            "X-MinerU-Task-Status-Url": _result_urls(task, request)[0],
            "X-MinerU-Task-Result-Url": _result_urls(task, request)[1],
        }
        return Response(content=data, media_type="application/zip", headers=headers)

    payload = _status_payload(task, request)
    return JSONResponse(
        status_code=200,
        content={
            **payload,
            "backend": task.backend,
            "version": "compatible",
            "results": _build_results(
                task,
                return_md=return_md,
                return_middle_json=return_middle_json,
                return_model_output=return_model_output,
                return_content_list=return_content_list,
                return_images=return_images,
            ),
        },
        headers={
            "X-MinerU-Task-Id": task.id,
            "X-MinerU-Task-Status": _task_status(task),
            "X-MinerU-Task-Status-Url": _result_urls(task, request)[0],
            "X-MinerU-Task-Result-Url": _result_urls(task, request)[1],
        },
    )
