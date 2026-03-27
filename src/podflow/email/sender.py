"""Resend email sender."""

from __future__ import annotations

import logging
import os

import resend

logger = logging.getLogger(__name__)


def _get_api_key() -> str:
    key = os.environ.get("RESEND_API_KEY", "")
    if not key:
        raise RuntimeError("RESEND_API_KEY not set. Add it to .env or environment.")
    return key


def send_email(subject: str, html: str, recipients: list[str], from_addr: str | None = None) -> None:
    """Send an HTML email via Resend."""
    resend.api_key = _get_api_key()
    sender = from_addr or os.environ.get("RESEND_FROM_ADDRESS", "Podflow <podflow@resend.dev>")

    params: resend.Emails.SendParams = {
        "from": sender,
        "to": recipients,
        "subject": subject,
        "html": html,
    }

    result = resend.Emails.send(params)
    logger.info(f"Email sent via Resend: {subject} -> {recipients} (id={result.get('id', 'unknown')})")
