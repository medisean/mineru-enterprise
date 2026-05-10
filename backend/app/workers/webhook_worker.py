"""
Celery worker — Webhook callback delivery tasks.

When a parse task completes (success/failed), the parse worker dispatches
a `deliver_webhook` task to the `webhook` queue. This task sends an HTTP POST
to the task's `callback_url` with an HMAC-SHA256 signature.

Payload format (matches MinerU official API):
{
    "task_id": "...",
    "data_id": "...",          # optional user-defined ID
    "status": "success|failed",
    "progress": 100,
    "error_message": null,
    "output_s3_prefix": "...", # S3 prefix for results
    "created_at": "...",
    "completed_at": "..."
}

Signature header: X-MinerU-Signature = HMAC-SHA256(payload_json, seed)
"""
import json
import hashlib
import hmac
import structlog
from datetime import datetime, timezone

import httpx
from celery import Celery

from app.core.config import settings

logger = structlog.get_logger(__name__)

# Reuse the same Celery app as parse_worker
from app.workers.parse_worker import celery_app


def _sign_payload(payload_json: str, seed: str) -> str:
    """Compute HMAC-SHA256 signature for the payload using the seed."""
    return hmac.new(seed.encode(), payload_json.encode(), hashlib.sha256).hexdigest()


@celery_app.task(
    bind=True,
    name="app.workers.webhook_worker.deliver_webhook",
    max_retries=settings.WEBHOOK_MAX_RETRIES,
    soft_time_limit=30,
    default_retry_delay=30,  # seconds, doubles each retry via countdown
)
def deliver_webhook(self, task_id: str, callback_url: str, callback_seed: str, payload: dict):
    """Send an HTTP POST callback to the given URL with HMAC signature."""
    if not settings.WEBHOOK_ENABLED:
        logger.info("Webhook disabled, skipping", task_id=task_id)
        return

    payload_json = json.dumps(payload, ensure_ascii=False, default=str)

    # Determine signing key: per-task seed > global WEBHOOK_SECRET
    seed = callback_seed or settings.WEBHOOK_SECRET or ""
    signature = _sign_payload(payload_json, seed) if seed else ""

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "MinerU-Webhook/1.0",
    }
    if signature:
        headers["X-MinerU-Signature"] = signature

    try:
        with httpx.Client(timeout=settings.WEBHOOK_TIMEOUT_SECONDS) as client:
            resp = client.post(callback_url, content=payload_json, headers=headers)

        if resp.status_code >= 400:
            logger.warning(
                "Webhook callback received error response",
                task_id=task_id,
                callback_url=callback_url,
                status_code=resp.status_code,
                body=resp.text[:500],
            )
            # Retry on server errors (5xx), not on client errors (4xx)
            if resp.status_code >= 500 and self.request.retries < self.max_retries:
                countdown = 30 * (2 ** self.request.retries)
                raise self.retry(countdown=countdown)
        else:
            logger.info(
                "Webhook callback delivered",
                task_id=task_id,
                callback_url=callback_url,
                status_code=resp.status_code,
            )

    except httpx.TimeoutException as exc:
        logger.warning("Webhook callback timed out, retrying", task_id=task_id, callback_url=callback_url)
        if self.request.retries < self.max_retries:
            countdown = 30 * (2 ** self.request.retries)
            raise self.retry(exc=exc, countdown=countdown)
        else:
            logger.error("Webhook callback failed after max retries", task_id=task_id, callback_url=callback_url)

    except httpx.ConnectError as exc:
        logger.warning("Webhook callback connection failed, retrying", task_id=task_id, callback_url=callback_url)
        if self.request.retries < self.max_retries:
            countdown = 30 * (2 ** self.request.retries)
            raise self.retry(exc=exc, countdown=countdown)
        else:
            logger.error("Webhook callback connection failed after max retries", task_id=task_id, callback_url=callback_url)

    except Exception as exc:
        logger.error("Webhook callback unexpected error", task_id=task_id, callback_url=callback_url, error=str(exc))
        if self.request.retries < self.max_retries:
            countdown = 30 * (2 ** self.request.retries)
            raise self.retry(exc=exc, countdown=countdown)


def dispatch_webhook(task_id: str, callback_url: str, callback_seed: str, status: str, **extra):
    """Fire-and-forget webhook delivery task."""
    payload = {
        "task_id": task_id,
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **extra,
    }
    deliver_webhook.apply_async(
        args=[task_id, callback_url, callback_seed, payload],
        queue="webhook",
    )
