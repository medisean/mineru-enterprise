"""
Celery worker — MinerU document parsing tasks.
"""
import os
import io
import zipfile
import signal
import tempfile
import time
import shutil
import structlog
from datetime import datetime, timezone
from pathlib import Path
from celery import Celery

from app.services.markdown_utils import convert_html_tables_to_markdown
from app.services.official_result_exports import (
    ensure_full_result_zip,
    normalize_extra_formats,
    render_extra_format_files,
)

from app.core.config import settings
from app.core.schema_compat import try_ensure_sync_schema_compat

logger = structlog.get_logger(__name__)

IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "bmp", "webp", "tiff"}

celery_app = Celery(
    "mineru_worker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "app.workers.parse_worker.parse_document_cpu": {"queue": "parse_cpu"},
        "app.workers.parse_worker.parse_document_gpu": {"queue": "parse_gpu"},
        "app.workers.webhook_worker.deliver_webhook": {"queue": "webhook"},
    },
)


# ── Reusable DB engine for Celery worker ─────────────────────────────────
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from celery.signals import worker_process_init

_sync_db_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg2")
_engine = create_engine(
    _sync_db_url,
    pool_size=5,
    max_overflow=3,
    pool_pre_ping=True,
    pool_recycle=1800,
)
_SessionFactory = sessionmaker(_engine)


def _ensure_worker_schema_compat(source: str = "parse_worker") -> None:
    try_ensure_sync_schema_compat(_engine, source=source)


_ensure_worker_schema_compat("parse_worker_import")


@worker_process_init.connect
def _on_worker_process_init(**_kwargs):
    _ensure_worker_schema_compat("worker_process_init")


MINERU_BACKEND_ALIASES = {
    "vlm-auto-engine": "vlm-engine",
    "hybrid-auto-engine": "hybrid-engine",
}


def _normalize_mineru_backend(backend: str) -> str:
    if not backend:
        backend = settings.MINERU_API_DEFAULT_BACKEND
    return MINERU_BACKEND_ALIASES.get(backend, backend)


def _run_parse(self, task_id: str, input_s3_key: str, output_s3_prefix: str, config: dict):
    """Shared parsing logic used by both CPU and GPU task variants."""
    import subprocess, json, glob

    # Use the module-level engine/session factory (connection pool is reused)
    _ensure_worker_schema_compat("parse_task_start")
    Session = _SessionFactory
    run_attempt = int(config.get("run_attempt") or 0)
    tmp_path = None

    def is_terminal_status(status) -> bool:
        from app.models.models import TaskStatus
        return status in {TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED}

    def update_task_status(status, progress=None, error=None, output_prefix=None):
        with Session() as session:
            from app.models.models import ParseTask, TaskStatus
            task = session.get(ParseTask, task_id)
            if task and task.run_attempt == run_attempt:
                if status == "processing" and is_terminal_status(task.status):
                    return False
                task.status = TaskStatus(status)
                if progress is not None:
                    task.progress = progress
                if error:
                    task.error_message = error
                if output_prefix:
                    task.output_s3_prefix = output_prefix
                if status == "processing":
                    now = datetime.now(timezone.utc)
                    if task.started_at is None:
                        task.started_at = now
                    task.last_heartbeat_at = now
                elif status in ("success", "failed"):
                    task.completed_at = datetime.now(timezone.utc)
                    task.last_heartbeat_at = None
                session.commit()

                # Fire webhook callback on terminal states
                if status in ("success", "failed") and task.callback_url:
                    try:
                        from app.workers.webhook_worker import dispatch_webhook
                        dispatch_webhook(
                            task_id=task_id,
                            callback_url=task.callback_url,
                            callback_seed=task.callback_seed or "",
                            status=status,
                            user_id=task.user_id,
                            data_id=task.data_id,
                            progress=task.progress,
                            error_message=task.error_message,
                            output_s3_prefix=task.output_s3_prefix,
                            created_at=task.created_at.isoformat() if task.created_at else None,
                            completed_at=task.completed_at.isoformat() if task.completed_at else None,
                        )
                    except Exception as e:
                        logger.warning("Failed to dispatch webhook", task_id=task_id, error=str(e))
                return True
            return False

    def task_can_run():
        with Session() as session:
            from app.models.models import ParseTask
            task = session.get(ParseTask, task_id)
            return bool(task and task.run_attempt == run_attempt and not is_terminal_status(task.status))

    def heartbeat(progress=None):
        with Session() as session:
            from app.models.models import ParseTask, TaskStatus
            task = session.get(ParseTask, task_id)
            if not task or task.run_attempt != run_attempt:
                return False
            if is_terminal_status(task.status):
                return False
            if task.status != TaskStatus.PROCESSING:
                task.status = TaskStatus.PROCESSING
            if progress is not None:
                task.progress = progress
            task.last_heartbeat_at = datetime.now(timezone.utc)
            session.commit()
            return True

    def terminate_process(process):
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=10)
        except Exception:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except Exception:
                pass

    try:
        if not task_can_run():
            return {"status": "cancelled", "output_prefix": output_s3_prefix, "files": []}
        if not update_task_status("processing", progress=5):
            return {"status": "cancelled", "output_prefix": output_s3_prefix, "files": []}
        self.update_state(state="PROGRESS", meta={"progress": 5, "message": "Downloading file"})

        from app.services.storage import storage_service

        # Download input from S3
        file_bytes = storage_service.download_bytes(input_s3_key)
        update_task_status("processing", progress=20)
        self.update_state(state="PROGRESS", meta={"progress": 20, "message": "File downloaded, parsing..."})

        # Write to temp file
        suffix = "." + input_s3_key.rsplit(".", 1)[-1].lower()
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        office_ext = _get_office_extension(input_s3_key)

        # Build MinerU CLI command with full parameter set
        backend = config.get("backend") or settings.MINERU_BACKEND
        device = config.get("device", settings.MINERU_DEVICE)
        language = config.get("language", "")
        is_ocr = config.get("is_ocr")
        enable_formula = config.get("enable_formula", True)
        enable_table = config.get("enable_table", True)
        page_ranges = config.get("page_ranges")
        parse_options = config.get("parse_options") or {}
        image_analysis = _parse_bool_option(
            parse_options.get("image-analysis", config.get("image_analysis")),
            settings.MINERU_DEFAULT_IMAGE_ANALYSIS,
        )
        extra_formats = normalize_extra_formats(config.get("extra_formats"), config.get("output_format"))
        server_url = (
            config.get("server_url")
            or parse_options.get("url")
            or parse_options.get("server-url")
        )
        api_url = (
            config.get("api_url")
            or parse_options.get("api-url")
            or settings.MINERU_API_URL
            or settings.MINERU_SERVER_URL
        )
        backend = _normalize_mineru_backend(str(backend or ""))

        with tempfile.TemporaryDirectory() as output_dir:
            cmd = [
                "mineru",
                "-p", tmp_path,
                "-o", output_dir,
            ]

            # MinerU 3.x CLI uses backend/method flags. Device is selected by
            # the worker image/runtime, not by a CLI --device flag.
            if backend:
                cmd += ["-b", backend]

            if is_ocr is True:
                cmd += ["-m", "ocr"]
            elif is_ocr is False:
                cmd += ["-m", "txt"]
            else:
                cmd += ["-m", "auto"]

            if language and language != "auto":
                cmd += ["-l", language]

            cmd += ["-f", _bool_cli(enable_formula)]
            cmd += ["-t", _bool_cli(enable_table)]
            cmd += ["--image-analysis", _bool_cli(image_analysis)]

            start_page, end_page = _page_range_to_start_end(page_ranges)
            if start_page is not None:
                cmd += ["-s", str(start_page)]
            if end_page is not None:
                cmd += ["-e", str(end_page)]

            if server_url:
                cmd += ["-u", str(server_url)]
            if api_url:
                cmd += ["--api-url", str(api_url)]

            # Any extra MinerU 3.x CLI options from parse_options.
            handled_options = {
                "url", "server-url", "api-url",
                "output-format", "device", "backend", "pages", "formats",
                "lang", "ocr", "formula", "table", "image-analysis",
            }
            for key, value in parse_options.items() if parse_options else []:
                if key in handled_options:
                    continue
                if value is True:
                    cmd.append(f"--{key}")
                elif value is False:
                    cmd.append(f"--no-{key}")
                elif value is not None:
                    cmd.extend([f"--{key}", str(value)])

            update_task_status("processing", progress=30)
            self.update_state(state="PROGRESS", meta={"progress": 30, "message": "Running MinerU parser..."})

            logger.info("MinerU command", cmd=" ".join(cmd), task_id=task_id)

            process = subprocess.Popen(
                cmd,
                start_new_session=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            previous_signal_handlers = {}

            def handle_parse_signal(signum, _frame):
                terminate_process(process)
                raise RuntimeError(f"Parse task terminated by signal {signum}")

            for signum in (signal.SIGTERM, signal.SIGINT):
                previous_signal_handlers[signum] = signal.getsignal(signum)
                signal.signal(signum, handle_parse_signal)

            stdout, stderr = "", ""
            started = time.monotonic()
            last_heartbeat = 0.0
            parse_timeout_seconds = max(int(settings.MINERU_PARSE_TIMEOUT_SECONDS), 30)
            try:
                while True:
                    if process.poll() is not None:
                        stdout, stderr = process.communicate()
                        break
                    now_monotonic = time.monotonic()
                    if now_monotonic - started > parse_timeout_seconds:
                        terminate_process(process)
                        raise TimeoutError(f"MinerU parsing timed out after {parse_timeout_seconds} seconds")
                    if now_monotonic - last_heartbeat >= settings.TASK_HEARTBEAT_INTERVAL_SECONDS:
                        if not heartbeat(progress=30):
                            terminate_process(process)
                            raise RuntimeError("Parse task was stopped or superseded")
                        last_heartbeat = now_monotonic
                    time.sleep(1)
            finally:
                for signum, previous_handler in previous_signal_handlers.items():
                    signal.signal(signum, previous_handler)

            # Log MinerU output for debugging (especially image parsing issues)
            if stdout:
                logger.info("MinerU stdout", task_id=task_id, output=_summarize_process_output(stdout))
            if stderr:
                logger.warning("MinerU stderr", task_id=task_id, output=_summarize_process_output(stderr))

            if process.returncode != 0:
                raise RuntimeError(f"MinerU error (exit {process.returncode}): {_summarize_process_output(stderr, head=2400, tail=3600)}")

            update_task_status("processing", progress=80)
            self.update_state(state="PROGRESS", meta={"progress": 80, "message": "Uploading results"})

            # Upload all output files to S3
            uploaded_files = []
            for root, dirs, files in os.walk(output_dir):
                for fname in files:
                    fpath = os.path.join(root, fname)
                    rel = os.path.relpath(fpath, output_dir)
                    s3_key = f"{output_s3_prefix}/{rel}"
                    content_type = _guess_content_type(fname)

                    # Post-process .md files: convert HTML tables to Markdown tables
                    # MinerU outputs raw HTML tables in Markdown for all backends
                    if fname.endswith(".md"):
                        with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                            raw = f.read()
                        converted = convert_html_tables_to_markdown(raw)
                        for extra_path, extra_content_type in render_extra_format_files(converted, fpath, extra_formats):
                            rel = os.path.relpath(extra_path, output_dir)
                            extra_s3_key = f"{output_s3_prefix}/{rel}"
                            with open(extra_path, "rb") as extra_file:
                                storage_service.upload_bytes(extra_s3_key, extra_file.read(), extra_content_type)
                            uploaded_files.append(extra_s3_key)
                        storage_service.upload_bytes(s3_key, converted.encode("utf-8"), content_type)
                    else:
                        with open(fpath, "rb") as f:
                            storage_service.upload_bytes(s3_key, f.read(), content_type)
                    uploaded_files.append(s3_key)

            # Convert Office source files (PPTX/DOCX/XLSX) to PDF for preview
            if office_ext:
                try:
                    pdf_path = _convert_office_to_pdf(tmp_path, office_ext)
                    if pdf_path and os.path.exists(pdf_path):
                        pdf_s3_key = f"{output_s3_prefix}/_preview/source_preview.pdf"
                        with open(pdf_path, "rb") as pf:
                            storage_service.upload_bytes(pdf_s3_key, pf.read(), "application/pdf")
                            uploaded_files.append(pdf_s3_key)
                        pdf_dir = os.path.dirname(pdf_path)
                        os.unlink(pdf_path)
                        shutil.rmtree(pdf_dir, ignore_errors=True)
                        logger.info("Office→PDF preview generated", task_id=task_id)
                except Exception as e:
                    logger.info("Office PDF preview unavailable; parse result is unaffected", task_id=task_id, error=str(e))

            full_zip_key = ensure_full_result_zip(storage_service, output_s3_prefix)
            if full_zip_key:
                uploaded_files.append(full_zip_key)
                uploaded_files.extend(
                    upload_missing_images_from_zip(storage_service, full_zip_key, output_s3_prefix)
                )

        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
        update_task_status("success", progress=100, output_prefix=output_s3_prefix)
        self.update_state(state="SUCCESS", meta={"progress": 100, "files": uploaded_files})
        return {"status": "success", "output_prefix": output_s3_prefix, "files": uploaded_files}

    except Exception as exc:
        logger.error("Parse task failed", task_id=task_id, error=str(exc))
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
        with Session() as session:
            from app.models.models import ParseTask, TaskStatus
            task = session.get(ParseTask, task_id)
            if not task or task.run_attempt != run_attempt or is_terminal_status(task.status):
                return {"status": "cancelled", "output_prefix": output_s3_prefix, "files": []}
        update_task_status("failed", error=str(exc))
        raise exc


def _guess_content_type(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    types = {
        "md": "text/markdown",
        "json": "application/json",
        "html": "text/html",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "bmp": "image/bmp",
        "webp": "image/webp",
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "latex": "application/x-latex",
        "tex": "application/x-latex",
    }
    return types.get(ext, "application/octet-stream")


def upload_missing_images_from_zip(storage_service, zip_key: str, output_s3_prefix: str) -> list[str]:
    uploaded: list[str] = []
    try:
        zip_data = storage_service.download_bytes(zip_key)
    except Exception as e:
        logger.warning("Failed to download result zip for image sync", zip_key=zip_key, error=str(e))
        return uploaded

    try:
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                rel = info.filename.lstrip("/")
                ext = rel.rsplit(".", 1)[-1].lower() if "." in rel else ""
                if ext not in IMAGE_EXTENSIONS:
                    continue
                s3_key = f"{output_s3_prefix.rstrip('/')}/{rel}"
                storage_service.upload_bytes(s3_key, zf.read(info), _guess_content_type(rel))
                uploaded.append(s3_key)
    except Exception as e:
        logger.warning("Failed to sync images from result zip", zip_key=zip_key, error=str(e))
    return uploaded


def _bool_cli(value) -> str:
    """Return MinerU 3.x boolean CLI value."""
    return "true" if bool(value) else "false"


def _summarize_process_output(value: str, head: int = 3000, tail: int = 5000) -> str:
    """Keep both ends of long subprocess logs so traceback root causes survive."""
    text = value or ""
    limit = head + tail
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    return f"{text[:head]}\n... <omitted {omitted} chars> ...\n{text[-tail:]}"


def _parse_bool_option(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _page_range_to_start_end(page_ranges: str | None) -> tuple[int | None, int | None]:
    """Convert a 1-based page range such as '1-10' or '2' to MinerU 0-based bounds."""
    if not page_ranges:
        return None, None
    first_range = str(page_ranges).split(",", 1)[0].strip()
    if not first_range:
        return None, None
    if "-" in first_range:
        start_raw, end_raw = first_range.split("-", 1)
    else:
        start_raw, end_raw = first_range, first_range
    try:
        start = max(int(start_raw.strip()) - 1, 0)
        end = max(int(end_raw.strip()) - 1, start)
        return start, end
    except ValueError:
        logger.warning("Invalid page range ignored", page_ranges=page_ranges)
        return None, None


def _get_office_extension(s3_key: str) -> str | None:
    """Return the office extension if the file is an Office document, else None."""
    ext = s3_key.rsplit(".", 1)[-1].lower() if "." in s3_key else ""
    office_exts = {"pptx", "docx", "xlsx"}
    return ext if ext in office_exts else None


def _office_pdf_filter(office_ext: str | None) -> str:
    filters = {
        "pptx": "pdf:impress_pdf_Export",
        "docx": "pdf:writer_pdf_Export",
        "xlsx": "pdf:calc_pdf_Export",
    }
    return filters.get((office_ext or "").lower(), "pdf")


def _convert_office_to_pdf(input_path: str, office_ext: str | None = None) -> str | None:
    """Convert an Office file to PDF using LibreOffice headless. Returns the PDF path or None."""
    import subprocess
    output_dir = tempfile.mkdtemp()
    user_profile_dir = tempfile.mkdtemp()
    home_dir = tempfile.mkdtemp()
    runtime_dir = tempfile.mkdtemp()
    pdf_path = None
    binaries = [b for b in ("libreoffice", "soffice") if shutil.which(b)]
    if not binaries:
        logger.warning("LibreOffice conversion unavailable: libreoffice/soffice not found")
        shutil.rmtree(output_dir, ignore_errors=True)
        shutil.rmtree(user_profile_dir, ignore_errors=True)
        shutil.rmtree(home_dir, ignore_errors=True)
        shutil.rmtree(runtime_dir, ignore_errors=True)
        return None

    try:
        os.chmod(runtime_dir, 0o700)
        env = os.environ.copy()
        env.update({
            "HOME": home_dir,
            "XDG_CACHE_HOME": os.path.join(home_dir, ".cache"),
            "XDG_CONFIG_HOME": os.path.join(home_dir, ".config"),
            "XDG_RUNTIME_DIR": runtime_dir,
            "SAL_USE_VCLPLUGIN": "svp",
            "JAVA_TOOL_OPTIONS": "-Djava.awt.headless=true",
        })
        convert_to = _office_pdf_filter(office_ext)
        last_stderr = ""
        for binary in binaries:
            result = subprocess.run(
                [
                    binary,
                    "--headless",
                    "--invisible",
                    "--nologo",
                    "--nofirststartwizard",
                    "--nodefault",
                    "--nolockcheck",
                    "--norestore",
                    f"-env:UserInstallation={Path(user_profile_dir).as_uri()}",
                    "--convert-to", convert_to,
                    "--outdir", output_dir,
                    input_path,
                ],
                capture_output=True,
                text=True,
                timeout=180,
                env=env,
            )
            last_stderr = result.stderr or result.stdout or ""
            if result.returncode == 0:
                break
        else:
            logger.info("LibreOffice preview conversion failed", stderr=_first_log_line(last_stderr))
            return None

        # Find the generated PDF
        for fname in os.listdir(output_dir):
            if fname.lower().endswith(".pdf"):
                pdf_path = os.path.join(output_dir, fname)
                return pdf_path
        logger.info("LibreOffice preview conversion produced no PDF", output_dir=output_dir)
        return None
    except Exception as e:
        logger.info("LibreOffice preview conversion exception", error=str(e))
        return None
    finally:
        shutil.rmtree(user_profile_dir, ignore_errors=True)
        shutil.rmtree(home_dir, ignore_errors=True)
        shutil.rmtree(runtime_dir, ignore_errors=True)
        if pdf_path is None:
            shutil.rmtree(output_dir, ignore_errors=True)


def _first_log_line(value: str, limit: int = 240) -> str:
    line = (value or "").strip().splitlines()
    return (line[0] if line else "")[:limit]


# ── CPU task entry point ───────────────────────────────────────────────────
@celery_app.task(
    bind=True,
    name="app.workers.parse_worker.parse_document_cpu",
    max_retries=0,
    soft_time_limit=3600,
)
def parse_document_cpu(self, task_id: str, input_s3_key: str, output_s3_prefix: str, config: dict):
    """Parse task dispatched to CPU worker queue."""
    config["device"] = "cpu"
    return _run_parse(self, task_id, input_s3_key, output_s3_prefix, config)


# ── GPU task entry point ───────────────────────────────────────────────────
@celery_app.task(
    bind=True,
    name="app.workers.parse_worker.parse_document_gpu",
    max_retries=0,
    soft_time_limit=3600,
)
def parse_document_gpu(self, task_id: str, input_s3_key: str, output_s3_prefix: str, config: dict):
    """Parse task dispatched to GPU worker queue."""
    config["device"] = config.get("device", "cuda")
    return _run_parse(self, task_id, input_s3_key, output_s3_prefix, config)


def dispatch_parse_task(task_id: str, input_s3_key: str, output_s3_prefix: str, config: dict) -> str:
    """Dispatch a parse task to the appropriate queue based on device / environment.

    Routing logic:
      - If config specifies device=cuda/mps → parse_gpu queue
      - If config specifies device=cpu       → parse_cpu queue
      - If FORCE_GPU_QUEUE=true (env var)     → parse_gpu queue (production mode)
      - Otherwise                            → parse_cpu queue (default / dev)
    """
    force_gpu = os.environ.get("FORCE_GPU_QUEUE", "").lower() in ("1", "true", "yes")
    device = config.get("device", settings.MINERU_DEVICE)

    if force_gpu or device in ("cuda", "mps"):
        result = parse_document_gpu.apply_async(
            args=[task_id, input_s3_key, output_s3_prefix, config],
            queue="parse_gpu",
        )
    else:
        result = parse_document_cpu.apply_async(
            args=[task_id, input_s3_key, output_s3_prefix, config],
            queue="parse_cpu",
        )

    return result.id
