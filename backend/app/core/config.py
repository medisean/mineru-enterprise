"""
Application Settings — all values read from environment variables.
"""
import sys
import warnings
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ── App ───────────────────────────────────────────────────────────────
    APP_NAME: str = "MinerU Enterprise"
    DEBUG: bool = False
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 1 day
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    def model_post_init(self, __context) -> None:
        """Validate critical security settings after loading from env."""
        if self.SECRET_KEY == "change-me-in-production" or self.SECRET_KEY == "change-me-to-a-random-secret-key-in-production":
            warnings.warn(
                "⚠️  SECRET_KEY is using the default value! "
                "JWT tokens can be forged. Set a strong SECRET_KEY in your .env file.",
                stacklevel=1,
            )
            if not self.DEBUG:
                # In production (DEBUG=false), refuse to start with default SECRET_KEY
                sys.exit(
                    "FATAL: SECRET_KEY must be changed from the default value in production. "
                    "Set a strong random SECRET_KEY in your .env file."
                )
        if not self.DEBUG and not self.ALLOWED_HOSTS:
            warnings.warn(
                "⚠️  ALLOWED_HOSTS is empty in production. "
                "Host header injection is possible. Set ALLOWED_HOSTS in your .env file.",
                stacklevel=1,
            )

    # ── Hosts & CORS ──────────────────────────────────────────────────────
    ALLOWED_HOSTS: List[str] = []  # Empty = allow all in dev; MUST set in production
    CORS_ORIGINS: List[str] = ["http://localhost:3000"]
    FRONTEND_URL: str = "http://localhost:3000"

    # ── Database ──────────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@postgres:5432/mineru"
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10

    # ── Redis / Celery ────────────────────────────────────────────────────
    REDIS_URL: str = "redis://redis:6379/0"
    CELERY_BROKER_URL: str = "redis://redis:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://redis:6379/2"

    # ── S3 / Object Storage ───────────────────────────────────────────────
    S3_ENDPOINT_URL: Optional[str] = None      # None = AWS, or MinIO/OSS endpoint
    S3_EXTERNAL_URL: Optional[str] = None      # URL accessible from browser (for presigned URLs)
    S3_ACCESS_KEY_ID: str = ""
    S3_SECRET_ACCESS_KEY: str = ""
    S3_REGION_NAME: str = "us-east-1"
    S3_BUCKET_NAME: str = "mineru-enterprise"
    S3_PRESIGN_EXPIRE_SECONDS: int = 3600

    # ── MinerU Engine ─────────────────────────────────────────────────────
    MINERU_BACKEND: str = ""                  # empty = MinerU default
    MINERU_API_DEFAULT_BACKEND: str = "pipeline"
    MINERU_SERVER_URL: str = ""                # persistent mineru-api base URL passed as CLI --api-url
    MINERU_API_URL: str = ""                   # optional MinerU API URL override passed through to CLI
    MINERU_DEVICE: str = "cpu"                 # cpu | cuda | mps
    MINERU_OUTPUT_FORMAT: str = "markdown"     # markdown | json | both

    # ── SSO — Generic OIDC ────────────────────────────────────────────────
    SSO_AUTO_LOGIN_ENABLED: bool = False
    SSO_DEFAULT_PROVIDER: str = "oidc"
    SSO_DEBUG_LOG_SECRETS: bool = False
    LOCAL_LOGIN_ENABLED: bool = True

    OIDC_ENABLED: bool = False
    OIDC_ISSUER: str = ""
    OIDC_CLIENT_ID: str = ""
    OIDC_CLIENT_SECRET: str = ""
    OIDC_SCOPE: str = "openid email profile"

    # ── SSO — Generic OAuth2 (IDaaS / custom IdP) ────────────────────────
    OAUTH2_ENABLED: bool = False
    OAUTH2_AUTHORIZATION_URL: str = ""
    OAUTH2_TOKEN_URL: str = ""
    OAUTH2_USERINFO_URL: str = ""
    OAUTH2_CLIENT_ID: str = ""
    OAUTH2_CLIENT_SECRET: str = ""
    OAUTH2_SCOPE: str = "openid email profile"
    OAUTH2_USERINFO_SCOPE: str = "base.profile"
    OAUTH2_TOKEN_AUTH_METHOD: str = "client_secret_post"  # client_secret_post | client_secret_basic
    OAUTH2_USER_ID_FIELD: str = "sub"
    OAUTH2_EMAIL_FIELD: str = "email"
    OAUTH2_NAME_FIELD: str = "name"
    OAUTH2_AVATAR_FIELD: str = "picture"

    # ── SSO — LDAP ────────────────────────────────────────────────────────
    LDAP_ENABLED: bool = False
    LDAP_SERVER: str = "ldap://ldap:389"
    LDAP_BIND_DN: str = ""
    LDAP_BIND_PASSWORD: str = ""
    LDAP_BASE_DN: str = "dc=example,dc=com"
    LDAP_USER_SEARCH_FILTER: str = "(uid={username})"
    LDAP_ATTR_EMAIL: str = "mail"
    LDAP_ATTR_NAME: str = "cn"

    # ── SSO — WeChat Work (企业微信) ──────────────────────────────────────
    WECHAT_WORK_ENABLED: bool = False
    WECHAT_WORK_CORP_ID: str = ""
    WECHAT_WORK_AGENT_ID: str = ""
    WECHAT_WORK_SECRET: str = ""

    # ── SSO — DingTalk (钉钉) ─────────────────────────────────────────────
    DINGTALK_ENABLED: bool = False
    DINGTALK_APP_KEY: str = ""
    DINGTALK_APP_SECRET: str = ""

    # ── Rate Limiting ─────────────────────────────────────────────────────
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_PER_MINUTE: int = 60

    # ── Webhook ───────────────────────────────────────────────────────────
    WEBHOOK_ENABLED: bool = True                    # master switch for outbound webhooks
    WEBHOOK_TIMEOUT_SECONDS: int = 10               # HTTP timeout per callback attempt
    WEBHOOK_MAX_RETRIES: int = 3                    # max retry attempts (exponential backoff)
    WEBHOOK_SECRET: str = ""                        # global HMAC key (if empty, per-task seed used)

    # ── Task Runtime Guardrails ─────────────────────────────────────────
    TASK_HEARTBEAT_INTERVAL_SECONDS: int = 15
    TASK_PENDING_STALLED_AFTER_SECONDS: int = 120
    TASK_STALLED_AFTER_SECONDS: int = 300
    TASK_WATCHDOG_INTERVAL_SECONDS: int = 60
    MINERU_PARSE_TIMEOUT_SECONDS: int = 1200

    # ── File Limits ───────────────────────────────────────────────────────
    MAX_UPLOAD_SIZE_MB: int = 50
    MAX_BATCH_FILES: int = 100
    ALLOWED_EXTENSIONS: List[str] = [
        "pdf",
        "png", "jpeg", "jp2", "webp", "gif", "bmp", "jpg", "tiff",
        "docx", "pptx", "xlsx",
    ]

    # ── MinerU Parse Options ─────────────────────────────────────────────
    MINERU_DEFAULT_OCR: Optional[bool] = None     # None=auto, True=force OCR, False=text-only
    MINERU_DEFAULT_ENABLE_FORMULA: bool = True
    MINERU_DEFAULT_ENABLE_TABLE: bool = True
    MINERU_DEFAULT_IMAGE_ANALYSIS: bool = False
    MINERU_DEFAULT_PAGE_RANGES: Optional[str] = None  # e.g. "1-10" or "2,4-6"
    MINERU_SUPPORTED_LANGUAGES: List[str] = [
        "ch", "ch_server", "ch_lite", "en", "japan", "korean", "chinese_cht",
        "ta", "te", "ka", "th", "el", "latin", "arabic", "east_slavic",
        "cyrillic", "devanagari",
    ]


settings = Settings()
