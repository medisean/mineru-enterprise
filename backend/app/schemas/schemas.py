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
    backend: Optional[str] = "pipeline"    # pipeline | vlm | MinerU-HTML
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
