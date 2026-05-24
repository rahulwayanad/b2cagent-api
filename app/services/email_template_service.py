"""Render and send transactional emails from the admin-managed templates.

All transactional mail in the app should route through `send_templated_email`
so subjects, bodies, and on/off switches are editable without code changes."""
from __future__ import annotations

import logging
import re
from string import Formatter
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import EmailTemplate
from app.services.email_shell import wrap_email_html
from app.services.notifications import EmailSender


_BADGE_BY_CODE: dict[str, tuple[str, str]] = {
    # code: (label, css class from email_shell)
    "otp": ("Verification", "badge-info"),
    "welcome": ("Welcome", "badge-info"),
    "bid_placed_agent": ("Bid placed", "badge-info"),
    "bid_placed_manager": ("New bid", "badge-info"),
    "bid_accepted": ("Bid accepted", "badge-success"),
    "bid_rejected": ("Bid declined", "badge-neutral"),
    "bid_held": ("Bid on hold", "badge-warn"),
    "bid_withdrawn": ("Bid withdrawn", "badge-neutral"),
    "booking_confirmed": ("Booking confirmed", "badge-success"),
    "profile_updated": ("Profile", "badge-neutral"),
    "subscription_limit_warning": ("Plan limit", "badge-warn"),
    "subscription_upgraded": ("Plan upgraded", "badge-success"),
}


_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")


def _looks_like_html(body: str) -> bool:
    return bool(_TAG_RE.search(body))


def _html_to_plain(html_body: str) -> str:
    """Best-effort fallback: strip tags so non-HTML clients still get a body."""
    text = re.sub(r"<br\s*/?>", "\n", html_body)
    text = re.sub(r"</p>", "\n\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    # Collapse runs of blank lines.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

logger = logging.getLogger("b2cagent.email")


class _SafeDict(dict):
    """str.format_map fallback that leaves unknown {keys} untouched instead
    of raising — keeps a typo in the admin UI from blowing up sends."""

    def __missing__(self, key: str) -> str:  # noqa: D401
        return "{" + key + "}"


def _render(text: str, context: dict[str, Any]) -> str:
    try:
        return text.format_map(_SafeDict(context))
    except Exception:  # noqa: BLE001
        logger.exception("email template render failed; using raw text")
        return text


async def get_template(db: AsyncSession, code: str) -> EmailTemplate | None:
    return await db.scalar(
        select(EmailTemplate).where(EmailTemplate.code == code)
    )


async def send_templated_email(
    db: AsyncSession,
    email_sender: EmailSender,
    *,
    code: str,
    to: str,
    context: dict[str, Any],
    fallback_subject: str | None = None,
    fallback_body: str | None = None,
) -> bool:
    """Look up the template by `code`, render with `context`, and send.

    Templates whose body contains HTML tags are sent as a styled HTML email
    (wrapped in the brand shell) with a plain-text alternative for older
    clients. Pure-text templates send as text only.

    Returns True if the mail was sent. Returns False (silently) when the
    template is missing/disabled and no fallback was provided, so callers
    can opt out of mailing without code changes when an admin disables it.
    """
    tmpl = await get_template(db, code)

    # Always make app/link URLs available to templates. Callers can override
    # `link_url` with a specific deep link; otherwise we fall back to the app root.
    base_url = settings.FRONTEND_BASE_URL.rstrip("/")
    context = {
        "app_url": base_url,
        "link_url": base_url,
        **context,
    }

    if tmpl is None or not tmpl.is_active:
        if fallback_subject is None or fallback_body is None:
            return False
        subject = _render(fallback_subject, context)
        raw_body = _render(fallback_body, context)
    else:
        subject = _render(tmpl.subject, context)
        raw_body = _render(tmpl.body, context)

    if _looks_like_html(raw_body):
        badge_label, badge_cls = _BADGE_BY_CODE.get(
            code, ("B2C Tour Agent", "badge-info")
        )
        html_body = wrap_email_html(
            subject=subject,
            body_html=raw_body,
            to=to,
            badge_label=badge_label,
            badge_cls=badge_cls,
        )
        plain_body = _html_to_plain(raw_body)
        await email_sender.send(
            to=to, subject=subject, body=plain_body, html_body=html_body
        )
    else:
        await email_sender.send(to=to, subject=subject, body=raw_body)
    return True


def extract_placeholders(text: str) -> list[str]:
    """Return the {placeholders} referenced in a template body/subject so the
    admin UI can show available variables."""
    names: list[str] = []
    for _, field, _, _ in Formatter().parse(text):
        if field and field not in names:
            names.append(field)
    return names
