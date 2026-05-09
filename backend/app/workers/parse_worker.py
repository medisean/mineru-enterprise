"""
Celery worker — MinerU document parsing tasks.
"""
import os
import io
import tempfile
import structlog
from datetime import datetime, timezone
from celery import Celery

from app.core.config import settings

logger = structlog.get_logger(__name__)

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
    },
)


# ── Reusable DB engine for Celery worker ─────────────────────────────────
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_sync_db_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg2")
_engine = create_engine(
    _sync_db_url,
    pool_size=5,
    max_overflow=3,
    pool_pre_ping=True,
    pool_recycle=1800,
)
_SessionFactory = sessionmaker(_engine)



def _run_parse(self, task_id: str, input_s3_key: str, output_s3_prefix: str, config: dict):
    """Shared parsing logic used by both CPU and GPU task variants."""
    import subprocess, json, glob

    # Use the module-level engine/session factory (connection pool is reused)
    Session = _SessionFactory

    def update_task_status(status, progress=None, error=None, output_prefix=None):
        with Session() as session:
            from app.models.models import ParseTask, TaskStatus
            task = session.get(ParseTask, task_id)
            if task:
                task.status = TaskStatus(status)
                if progress is not None:
                    task.progress = progress
                if error:
                    task.error_message = error
                if output_prefix:
                    task.output_s3_prefix = output_prefix
                if status == "processing":
                    task.started_at = datetime.now(timezone.utc)
                elif status in ("success", "failed"):
                    task.completed_at = datetime.now(timezone.utc)
                session.commit()

    try:
        update_task_status("processing", progress=5)
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

        # Build MinerU CLI command with full parameter set
        backend = config.get("backend", settings.MINERU_BACKEND)
        device = config.get("device", settings.MINERU_DEVICE)
        output_format = config.get("output_format", settings.MINERU_OUTPUT_FORMAT)
        language = config.get("language", "")
        is_ocr = config.get("is_ocr")
        enable_formula = config.get("enable_formula", True)
        enable_table = config.get("enable_table", True)
        page_ranges = config.get("page_ranges")
        parse_options = config.get("parse_options", {})

        with tempfile.TemporaryDirectory() as output_dir:
            cmd = [
                "mineru",
                "-p", tmp_path,
                "-o", output_dir,
            ]

            # Device selection (cpu | cuda | mps)
            if device and device != "cpu":
                cmd += ["--device", device]

            # Backend model selection (omit if empty → MinerU uses its default hybrid-auto-engine)
            if backend:
                cmd += ["--backend", backend]

            # Output format: MinerU uses --output-format for md/json
            # For docx/html/latex, we use the --formats extra flag
            if output_format in ("markdown", "md"):
                cmd += ["--output-format", "md"]
            elif output_format == "json":
                cmd += ["--output-format", "json"]
            elif output_format == "both":
                # MinerU outputs both by default; just run normally
                pass
            else:
                # docx / html / latex — MinerU supports extra export formats
                cmd += ["--output-format", "md"]
                # Extra formats handled in post-processing or by MinerU --formats
                if output_format in ("docx", "html", "latex"):
                    cmd += ["--formats", output_format]

            # Language
            if language and language != "auto":
                cmd += ["--lang", language]

            # OCR toggle (only add flag when explicitly True)
            if is_ocr is True:
                cmd.append("--ocr")
            elif is_ocr is False:
                cmd.append("--no-ocr")

            # Formula recognition
            if enable_formula is False:
                cmd.append("--no-formula")

            # Table recognition
            if enable_table is False:
                cmd.append("--no-table")

            # Page ranges
            if page_ranges:
                cmd += ["--pages", page_ranges]

            # Any extra CLI options from parse_options
            for key, value in parse_options.items() if parse_options else []:
                if value is True:
                    cmd.append(f"--{key}")
                elif value is False:
                    cmd.append(f"--no-{key}")
                elif value is not None:
                    cmd.extend([f"--{key}", str(value)])

            update_task_status("processing", progress=30)
            self.update_state(state="PROGRESS", meta={"progress": 30, "message": "Running MinerU parser..."})

            logger.info("MinerU command", cmd=" ".join(cmd), task_id=task_id)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3000,
            )

            # Log MinerU output for debugging (especially image parsing issues)
            if result.stdout:
                logger.info("MinerU stdout", task_id=task_id, output=result.stdout[:3000])
            if result.stderr:
                logger.warning("MinerU stderr", task_id=task_id, output=result.stderr[:3000])

            if result.returncode != 0:
                raise RuntimeError(f"MinerU error (exit {result.returncode}): {result.stderr[:2000]}")

            update_task_status("processing", progress=80)
            self.update_state(state="PROGRESS", meta={"progress": 80, "message": "Uploading results"})

            # Upload all output files to S3
            uploaded_files = []
            for root, dirs, files in os.walk(output_dir):
                for fname in files:
                    fpath = os.path.join(root, fname)
                    rel = os.path.relpath(fpath, output_dir)
                    s3_key = f"{output_s3_prefix}/{rel}"
                    with open(fpath, "rb") as f:
                        content_type = _guess_content_type(fname)
                        storage_service.upload_bytes(s3_key, f.read(), content_type)
                        uploaded_files.append(s3_key)

            # Convert Office source files (PPTX/DOCX/XLSX) to PDF for preview
            office_ext = _get_office_extension(input_s3_key)
            if office_ext:
                try:
                    pdf_path = _convert_office_to_pdf(tmp_path)
                    if pdf_path and os.path.exists(pdf_path):
                        pdf_s3_key = f"{output_s3_prefix}/_preview/source_preview.pdf"
                        with open(pdf_path, "rb") as pf:
                            storage_service.upload_bytes(pdf_s3_key, pf.read(), "application/pdf")
                            uploaded_files.append(pdf_s3_key)
                        os.unlink(pdf_path)
                        logger.info("Office→PDF preview generated", task_id=task_id)
                except Exception as e:
                    logger.warning("Office→PDF conversion failed, skipping preview", task_id=task_id, error=str(e))

        os.unlink(tmp_path)
        update_task_status("success", progress=100, output_prefix=output_s3_prefix)
        self.update_state(state="SUCCESS", meta={"progress": 100, "files": uploaded_files})
        return {"status": "success", "output_prefix": output_s3_prefix, "files": uploaded_files}

    except Exception as exc:
        logger.error("Parse task failed", task_id=task_id, error=str(exc))
        update_task_status("failed", error=str(exc))
        raise self.retry(exc=exc, countdown=30) if self.request.retries < self.max_retries else exc


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


def _get_office_extension(s3_key: str) -> str | None:
    """Return the office extension if the file is an Office document, else None."""
    ext = s3_key.rsplit(".", 1)[-1].lower() if "." in s3_key else ""
    office_exts = {"pptx", "docx", "xlsx"}
    return ext if ext in office_exts else None


def _convert_office_to_pdf(input_path: str) -> str | None:
    """Convert an Office file to PDF using LibreOffice headless. Returns the PDF path or None."""
    import subprocess
    output_dir = tempfile.mkdtemp()
    try:
        result = subprocess.run(
            [
                "libreoffice", "--headless", "--convert-to", "pdf",
                "--outdir", output_dir,
                input_path,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            logger.warning("LibreOffice conversion failed", stderr=result.stderr[:500])
            return None

        # Find the generated PDF
        for fname in os.listdir(output_dir):
            if fname.endswith(".pdf"):
                return os.path.join(output_dir, fname)
        return None
    except Exception as e:
        logger.warning("LibreOffice conversion exception", error=str(e))
        return None


# ── CPU task entry point ───────────────────────────────────────────────────
@celery_app.task(
    bind=True,
    name="app.workers.parse_worker.parse_document_cpu",
    max_retries=2,
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
    max_retries=2,
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
