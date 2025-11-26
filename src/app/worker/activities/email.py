# worker/activities/email.py
from __future__ import annotations

import hashlib
import os

import httpx
from temporalio import activity
from temporalio.exceptions import ApplicationError

from src.app.worker.registry import activity_defn

EMAIL_API_URL = os.getenv(
    "EMAIL_API_URL"
)  # e.g., https://api.sendgrid.com/v3/mail/send
EMAIL_API_KEY = os.getenv("EMAIL_API_KEY")  # provider secret
EMAIL_FROM = os.getenv("EMAIL_FROM", "no-reply@example.com")
HTTP_TIMEOUT = float(os.getenv("EMAIL_HTTP_TIMEOUT", "10.0"))


def _idempotency_key(to: str, subject: str, body: str) -> str:
    """Stable key so provider won’t send duplicates across retries."""
    info = activity.info()
    payload_hash = hashlib.sha256(
        (to + "\x1f" + subject + "\x1f" + body).encode("utf-8")
    ).hexdigest()
    # Include workflow+activity identity so the same logical send is stable across attempts/runs.
    return f"email:{info.workflow_id}:{info.activity_id}:{payload_hash}"


@activity_defn(queue="email")
async def send_email(to: str, subject: str, body: str) -> None:
    """
    Send an email via an HTTP provider.
    Temporal will retry this activity on transient failures per your RetryPolicy.
    We make the provider call idempotent so retries don't duplicate emails.
    """
    if not EMAIL_API_URL or not EMAIL_API_KEY:
        # Configuration error is not transient → mark non-retryable
        raise ApplicationError(
            "Email provider not configured",
            type="ConfigurationError",
            non_retryable=True,
        )

    idem_key = _idempotency_key(to, subject, body)

    # Example JSON shaped like many providers (adjust for your vendor)
    payload = {
        "from": {"email": EMAIL_FROM},
        "personalizations": [{"to": [{"email": to}], "subject": subject}],
        "content": [{"type": "text/plain", "value": body}],
    }

    headers = {
        "Authorization": f"Bearer {EMAIL_API_KEY}",
        # Most providers support an idempotency header; check your vendor.
        # For SendGrid you can safely use your own header (they’ll ignore unknown),
        # for others use what's documented (e.g., "Idempotency-Key", "X-Idempotency-Key").
        "Idempotency-Key": idem_key,
        "Content-Type": "application/json",
        "User-Agent": "temporal-worker/ email-activity",
    }

    # Short network timeouts; let Temporal control overall retries/backoff.
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(EMAIL_API_URL, json=payload, headers=headers)

    # Classify errors: 5xx → transient (let Temporal retry); 4xx → likely non-retryable.
    if 200 <= resp.status_code < 300:
        return

    if 500 <= resp.status_code < 600:
        # Transient; let RetryPolicy handle it by raising a normal Exception
        raise RuntimeError(f"Provider 5xx: {resp.status_code} {resp.text[:200]}")

    # 4xx: treat as permanent unless you explicitly whitelist retryable ones (e.g., 429)
    if resp.status_code == 429:
        # Too Many Requests: transient in practice → let it retry
        raise RuntimeError(f"Provider 429: {resp.text[:200]}")

    raise ApplicationError(
        f"Email send failed {resp.status_code}: {resp.text[:200]}",
        type="ValidationError",
        non_retryable=True,
    )
