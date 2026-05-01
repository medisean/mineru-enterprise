"""
Pydantic schemas for request/response validation.
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr, field_validator
import re


# ─── Auth ────────────────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class SSOCallbackRequest(BaseModel):
    code: str
    state: str
    provider: str  # oidc | wechat_work | dingtalk


# ─── User ────────────────────────────────────────────────────────────────────
class UserCreate(BaseModel):
    email: EmailStr
    username: str
    password: str
    full_name: Optional[str] = None

    @field_validator("username")
    @classmethod
    def username_valid(cls, v):
        if not re.match(r"^[a-zA-Z0-9_-]{3,32}$", v):
            raise ValueError("Username must be 3-32 chars, alphanumeric/underscore/hyphen only")
        return v


class UserOut(BaseModel):
    id: str
    email: str
    username: str
    full_name: Optional[str]
    avatar_url: Optional[str]
    role: str
    sso_provider: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── Upload ───────────────────────────────────────────────────────────────────
class PresignedUploadRequest(BaseModel):
    filename: str
    content_type: str
    file_size_bytes: int


class PresignedUploadResponse(BaseModel):
    upload_url: str
    s3_key: str
    expires_in: int


# ─── Tasks ───────────────────────────────────────────────────────────────────
class CreateTaskRequest(BaseModel):
    s3_key: str
    original_filename: str
    file_size_bytes: int
    backend: Optional[str] = ""    # pipeline | hybrid-auto-engine | vlm-auto-engine | empty=MinerU default
    output_format: Optional[str] = "markdown"   # markdown | json | both | docx | html | latex
    language: Optional[str] = "ch"         # ch | en | japan | korean | ch_server | ...
    is_ocr: Optional[bool] = None          # None = auto-detect
    enable_formula: Optional[bool] = True
    enable_table: Optional[bool] = True
    page_ranges: Optional[str] = None      # e.g. "1-10" or "2,4-6"
    parse_options: Optional[dict] = None   # extra MinerU CLI options


class TaskOut(BaseModel):
    id: str
    original_filename: str
    file_size_bytes: int
    status: str
    progress: int
    backend: str
    output_format: str
    error_message: Optional[str]
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    output_s3_prefix: Optional[str]

    model_config = {"from_attributes": True}


class TaskListResponse(BaseModel):
    items: List[TaskOut]
    total: int
    page: int
    page_size: int


class TaskResultFile(BaseModel):
    filename: str
    s3_key: str
    download_url: str
    size: int


class TaskResultResponse(BaseModel):
    task_id: str
    status: str
    files: List[TaskResultFile]


# ─── Org ──────────────────────────────────────────────────────────────────────
class OrgCreate(BaseModel):
    name: str
    slug: str
    quota_mb: int = 10240


class OrgOut(BaseModel):
    id: str
    name: str
    slug: str
    quota_mb: int
    max_concurrent_tasks: int
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── MinerU Official API Compatible Schemas ─────────────────────────────────

# --- Common response wrapper (matches MinerU official format) ---
class MinerUResponse(BaseModel):
    """Standard MinerU API response wrapper: {code, msg, trace_id, data}"""
    code: int = 0
    msg: str = "ok"
    trace_id: Optional[str] = None
    data: Optional[dict] = None


# --- Precision API: single file extract ---

class ExtractTaskRequest(BaseModel):
    """POST /api/v4/extract/task — create parse task by file URL"""
    url: str
    model_version: Optional[str] = ""       # pipeline | hybrid-auto-engine | vlm-auto-engine | empty=default
    is_ocr: Optional[bool] = False
    enable_formula: Optional[bool] = True
    enable_table: Optional[bool] = True
    language: Optional[str] = "ch"
    data_id: Optional[str] = None                    # user-defined ID, ≤128 chars
    callback: Optional[str] = None                   # callback URL
    seed: Optional[str] = None                       # callback signature seed
    extra_formats: Optional[List[str]] = None        # ["docx","html","latex"]
    page_ranges: Optional[str] = None
    no_cache: Optional[bool] = False
    cache_tolerance: Optional[int] = 900


class ExtractTaskData(BaseModel):
    task_id: str


class ExtractProgress(BaseModel):
    extracted_pages: int = 0
    total_pages: int = 0
    start_time: Optional[str] = None


class ExtractTaskResultData(BaseModel):
    """Response data for GET /api/v4/extract/task/{task_id}"""
    task_id: str
    data_id: Optional[str] = None
    state: str                                        # done | pending | running | failed | converting
    full_zip_url: Optional[str] = None
    err_msg: Optional[str] = ""
    extract_progress: Optional[ExtractProgress] = None


# --- Precision API: batch file upload ---

class BatchFileItem(BaseModel):
    """Single file entry in batch upload request"""
    name: str
    is_ocr: Optional[bool] = False
    data_id: Optional[str] = None
    page_ranges: Optional[str] = None


class BatchFileUrlsRequest(BaseModel):
    """POST /api/v4/file-urls/batch — get presigned upload URLs for batch"""
    files: List[BatchFileItem]                        # ≤50 items
    enable_formula: Optional[bool] = True
    enable_table: Optional[bool] = True
    language: Optional[str] = "ch"
    callback: Optional[str] = None
    seed: Optional[str] = None
    extra_formats: Optional[List[str]] = None
    model_version: Optional[str] = ""


class BatchFileUrlsData(BaseModel):
    batch_id: str
    file_urls: List[str]


# --- Precision API: batch URL extract ---

class BatchUrlFileItem(BaseModel):
    """Single URL file entry in batch extract request"""
    url: str
    is_ocr: Optional[bool] = False
    data_id: Optional[str] = None
    page_ranges: Optional[str] = None


class BatchUrlExtractRequest(BaseModel):
    """POST /api/v4/extract/task/batch — batch parse by URLs"""
    files: List[BatchUrlFileItem]                     # ≤50 items
    enable_formula: Optional[bool] = True
    enable_table: Optional[bool] = True
    language: Optional[str] = "ch"
    callback: Optional[str] = None
    seed: Optional[str] = None
    extra_formats: Optional[List[str]] = None
    model_version: Optional[str] = ""
    no_cache: Optional[bool] = False
    cache_tolerance: Optional[int] = 900


class BatchUrlExtractData(BaseModel):
    batch_id: str


# --- Precision API: batch results ---

class BatchExtractResultItem(BaseModel):
    file_name: str
    state: str
    full_zip_url: Optional[str] = None
    err_msg: Optional[str] = ""
    data_id: Optional[str] = None
    extract_progress: Optional[ExtractProgress] = None


class BatchExtractResultData(BaseModel):
    batch_id: str
    extract_result: List[BatchExtractResultItem]


# --- Agent lightweight API ---

class AgentUrlParseRequest(BaseModel):
    """POST /api/v1/agent/parse/url — lightweight parse by URL"""
    url: str
    file_name: Optional[str] = None
    language: Optional[str] = "ch"
    enable_table: Optional[bool] = True
    is_ocr: Optional[bool] = False
    enable_formula: Optional[bool] = True
    page_range: Optional[str] = None                  # Agent uses "page_range" (singular)


class AgentFileParseRequest(BaseModel):
    """POST /api/v1/agent/parse/file — lightweight parse by file upload"""
    file_name: str
    language: Optional[str] = "ch"
    enable_table: Optional[bool] = True
    is_ocr: Optional[bool] = False
    enable_formula: Optional[bool] = True
    page_range: Optional[str] = None


class AgentParseData(BaseModel):
    task_id: str
    file_url: Optional[str] = None                    # presigned upload URL (file mode only)


class AgentParseResultData(BaseModel):
    task_id: str
    state: str                                        # waiting-file | uploading | pending | running | done | failed
    markdown_url: Optional[str] = None
    err_msg: Optional[str] = ""
    err_code: Optional[int] = None
