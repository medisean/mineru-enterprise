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

    @field_validator("password")
    @classmethod
    def password_strength(cls, v):
        """Enforce password strength: ≥8 chars, at least 1 letter and 1 digit."""
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        if not re.search(r"[a-zA-Z]", v):
            raise ValueError("Password must contain at least one letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
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
    is_superuser: bool
    organization_id: Optional[str] = None
    created_at: datetime
    last_login_at: Optional[datetime] = None

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
    language: Optional[str] = ""          # empty=auto-detect | ch | en | japan | korean | ...
    is_ocr: Optional[bool] = None          # None = auto-detect
    enable_formula: Optional[bool] = True
    enable_table: Optional[bool] = True
    page_ranges: Optional[str] = None      # e.g. "1-10" or "2,4-6"
    data_id: Optional[str] = None          # user-defined business ID, ≤128 chars
    parse_options: Optional[dict] = None   # extra MinerU CLI options (whitelist-validated)
    callback_url: Optional[str] = None     # webhook URL to POST on task completion
    callback_seed: Optional[str] = None    # HMAC signature seed for webhook verification

    @field_validator("parse_options")
    @classmethod
    def validate_parse_options(cls, v):
        if v is None:
            return v
        # Whitelist of allowed MinerU CLI option keys
        ALLOWED_KEYS = {
            "auto-detect-direction", "lang", "ocr", "formula", "table",
            "output-format", "device", "backend", "pages", "formats",
            "url", "server-url", "api-url", "image-analysis",
        }
        for key in v:
            # Reject keys not in whitelist
            if key not in ALLOWED_KEYS:
                raise ValueError(f"parse_options key '{key}' is not allowed. Allowed keys: {sorted(ALLOWED_KEYS)}")
            # Reject keys containing shell metacharacters
            if any(c in key for c in ";&|`$(){}[]<>!#\n\r\t"):
                raise ValueError(f"parse_options key '{key}' contains invalid characters")
            # Validate values — must be str, bool, int, or float
            val = v[key]
            if not isinstance(val, (str, bool, int, float, type(None))):
                raise ValueError(f"parse_options['{key}'] must be a string, boolean, or number")
            if isinstance(val, str) and any(c in val for c in ";&|`$(){}[]<>!\n\r"):
                raise ValueError(f"parse_options['{key}'] value contains invalid characters")
        return v

    @field_validator("data_id")
    @classmethod
    def validate_data_id(cls, v):
        if v is not None and len(v) > 128:
            raise ValueError("data_id must be ≤128 characters")
        return v


class TaskOut(BaseModel):
    id: str
    original_filename: str
    file_size_bytes: int
    status: str
    progress: int
    is_favorite: bool = False
    backend: str
    output_format: str
    data_id: Optional[str] = None
    callback_url: Optional[str] = None
    error_message: Optional[str]
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    output_s3_prefix: Optional[str]
    queued_ahead: Optional[int] = None
    last_heartbeat_at: Optional[datetime] = None
    is_stalled: bool = False
    run_attempt: int = 0

    model_config = {"from_attributes": True}


class TaskListResponse(BaseModel):
    items: List[TaskOut]
    total: int
    page: int
    page_size: int


class TaskFavoriteRequest(BaseModel):
    is_favorite: bool


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
    files: List[BatchFileItem]                        # ≤100 items by default
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
    files: List[BatchUrlFileItem]                     # ≤100 items by default
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


# ─── Admin ──────────────────────────────────────────────────────────────────

class AdminUserOut(BaseModel):
    id: str
    email: str
    username: str
    full_name: Optional[str]
    avatar_url: Optional[str]
    role: str
    sso_provider: str
    is_active: bool
    is_superuser: bool
    organization_id: Optional[str] = None
    organization_name: Optional[str] = None
    created_at: datetime
    last_login_at: Optional[datetime] = None
    task_count: int = 0

    model_config = {"from_attributes": True}


class AdminUserUpdate(BaseModel):
    role: Optional[str] = None            # admin | member
    is_active: Optional[bool] = None
    organization_id: Optional[str] = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, v):
        if v is not None and v not in ("admin", "member"):
            raise ValueError("Role must be admin or member")
        return v


class AdminUserListResponse(BaseModel):
    items: List[AdminUserOut]
    total: int
    page: int
    page_size: int


class AdminOrgOut(BaseModel):
    id: str
    name: str
    slug: str
    quota_mb: int
    max_concurrent_tasks: int
    created_at: datetime
    member_count: int = 0
    task_count: int = 0
    storage_used_mb: float = 0

    model_config = {"from_attributes": True}


class AdminOrgCreate(BaseModel):
    name: str
    slug: str
    quota_mb: int = 10240
    max_concurrent_tasks: int = 5

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v):
        if not re.match(r"^[a-zA-Z0-9_-]{2,64}$", v):
            raise ValueError("Slug must be 2-64 chars, alphanumeric/underscore/hyphen only")
        return v


class AdminOrgUpdate(BaseModel):
    name: Optional[str] = None
    quota_mb: Optional[int] = None
    max_concurrent_tasks: Optional[int] = None


class AdminOrgListResponse(BaseModel):
    items: List[AdminOrgOut]
    total: int
    page: int
    page_size: int


class AdminRecentUser(BaseModel):
    id: str
    username: str
    email: str
    created_at: datetime


class AdminStatsOut(BaseModel):
    total_users: int
    total_tasks: int
    tasks_by_status: dict       # {"pending": N, "processing": N, ...}
    total_storage_mb: float
    recent_users: List[AdminRecentUser]


class AdminTaskOut(BaseModel):
    id: str
    original_filename: str
    file_size_bytes: int
    status: str
    progress: int
    backend: str
    username: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_s: Optional[int] = None       # seconds
    error_message: Optional[str] = None

    model_config = {"from_attributes": True}


class AdminTaskListResponse(BaseModel):
    items: List[AdminTaskOut]
    total: int
    page: int
    page_size: int


class AdminApiTokenOut(BaseModel):
    id: str
    name: str
    prefix: str
    suffix: str
    is_active: bool
    created_by_user_id: str
    created_by_username: Optional[str] = None
    created_at: datetime
    last_used_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class AdminApiTokenCreate(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        name = v.strip()
        if not name:
            raise ValueError("Name is required")
        if len(name) > 128:
            raise ValueError("Name must be 128 characters or fewer")
        return name


class AdminApiTokenCreateResponse(BaseModel):
    token: str
    item: AdminApiTokenOut


class AdminApiTokenUpdate(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def validate_update_name(cls, v):
        if v is None:
            return v
        name = v.strip()
        if not name:
            raise ValueError("Name is required")
        if len(name) > 128:
            raise ValueError("Name must be 128 characters or fewer")
        return name
