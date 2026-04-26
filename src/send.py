"""Deliver the digest email via Resend."""

import logging
import os

import resend

logger = logging.getLogger(__name__)


def send(html: str, subscribers: list[str], sender_email: str, subject: str | None = None) -> None:
    resend.api_key = os.environ["RESEND_API_KEY"]

    if subject is None:
        from datetime import datetime, timezone
        date = datetime.now(timezone.utc).strftime("%B %-d, %Y")
        subject = f"Claude Ecosystem Digest — {date}"

    logger.info("stage=send sending to %d subscriber(s)", len(subscribers))

    for recipient in subscribers:
        try:
            resend.Emails.send(
                {
                    "from": sender_email,
                    "to": [recipient],
                    "subject": subject,
                    "html": html,
                }
            )
        except Exception as exc:
            err_str = str(exc)
            if "422" in err_str or "domain" in err_str.lower() or "sender" in err_str.lower():
                raise RuntimeError(
                    "stage=send Resend returned 422: sender domain is not verified. "
                    "Add and verify your domain at resend.com/domains, then update "
                    "'sender_email' in config.yaml to use that domain."
                ) from exc
            if "401" in err_str or "api_key" in err_str.lower() or "unauthorized" in err_str.lower():
                raise RuntimeError(
                    "stage=send Resend API key is invalid or missing. "
                    "Check your key at resend.com/api-keys."
                ) from exc
            if "invalid" in err_str.lower() and "email" in err_str.lower():
                raise RuntimeError(
                    f"stage=send Resend rejected the recipient address — check SUBSCRIBER_EMAILS"
                ) from exc
            raise RuntimeError(f"stage=send Resend error: {exc}") from exc

    logger.info("stage=send delivered to %d subscriber(s)", len(subscribers))
