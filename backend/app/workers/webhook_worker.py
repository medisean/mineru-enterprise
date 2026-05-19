"""
Celery worker — Webhook callback delivery tasks.

When a parse task completes (success/failed), the parse worker dispatches
a `deliver_webhook` task to the `webhook` queue. This task sends an HTTP POST
to the task's `callback_url` using MinerU's official checksum/content body.

Payload format (matches MinerU official API):
{
    "checksum": "sha256(user_id + seed + content)",
    "content": "{\"task_id\":\"...\",\"state\":\"done\",...}"
}
"""
import json
import hashlib
import structlog
from datetime import datetime, timezone

import httpx
from celery import Celery

from app.core.config import settings

logger = structlog.get_logger(__name__)

# Reuse the same Celery app as parse_worker
from app.workers.parse_worker import celery_app


def _official_state(status: str) -> str:
    if status == "success":
        return "done"
    if status == "failed":
        return "failed"
    return status


def _build_official_content(task_id: str, payload: dict) -> str:
    data = {
        "task_id": task_id,
        "state": _official_state(str(payload.get("status") or "")),
        "err_msg": payload.get("error_message") or "",
    }
    if payload.get("data_id"):
        data["data_id"] = payload["data_id"]

    output_prefix = payload.get("output_s3_prefix")
    if data["state"] == "done" and output_prefix:
        try:
            from app.services.official_result_exports import ensure_full_result_zip
            from app.services.storage import storage_service
            zip_key = ensure_full_result_zip(storage_service, output_prefix)
            if zip_key:
                data["full_zip_url"] = storage_service.generate_download_presigned_url(zip_key)
        except Exception as exc:
            logger.warning("Failed to attach callback full_zip_url", task_id=task_id, error=str(exc))

    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _checksum(user_id: str, seed: str, content: str) -> str:
    """Compute official MinerU callback checksum."""
    return hashlib.sha256(f"{user_id}{seed}{content}".encode("utf-8")).hexdigest()


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

    content = _build_official_content(task_id, payload)
    seed = callback_seed or settings.WEBHOOK_SECRET or ""
    body = {
        "checksum": _checksum(str(payload.get("user_id") or ""), seed, content),
        "content": content,
    }
    payload_json = json.dumps(body, ensure_ascii=False, default=str)

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "MinerU-Webhook/1.0",
    }

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
