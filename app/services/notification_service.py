"""Single entrypoint for emitting in-app notifications + transactional emails.

Bid endpoints call these helpers when state changes; we record an in-app
notification AND fire the corresponding templated email so external delivery
is consistent with what the user sees inside the app."""
from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Bid, Notification, Property, User
from app.services.email_template_service import send_templated_email
from app.services.notifications import get_email_sender

logger = logging.getLogger("b2cagent.notify")


async def _email(
    db: AsyncSession,
    *,
    code: str,
    to: str | None,
    context: dict[str, Any],
    link: str | None = None,
) -> None:
    """Best-effort templated email send. Swallows errors — a flaky SMTP server
    should never break the bid action that triggered the notification.

    `link` is the in-app path the email's CTA should open (e.g. "/agent/bids");
    it gets joined to `FRONTEND_BASE_URL` and injected as `{link_url}`.
    """
    if not to:
        return
    if link:
        context = {
            **context,
            "link_url": f"{settings.FRONTEND_BASE_URL.rstrip('/')}{link}",
        }
    try:
        await send_templated_email(
            db, get_email_sender(), code=code, to=to, context=context
        )
    except Exception:  # noqa: BLE001
        logger.exception("templated email %s failed", code)


async def _notify(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    event: str,
    title: str,
    body: str,
    audience_role: str | None,
    link: str | None = None,
    related_bid_id: uuid.UUID | None = None,
) -> None:
    db.add(
        Notification(
            user_id=user_id,
            event=event,
            audience_role=audience_role,
            title=title,
            body=body,
            link=link,
            related_bid_id=related_bid_id,
        )
    )


def _money(d: Decimal) -> str:
    return f"₹{d:,.0f}"


async def _property_with_manager(
    db: AsyncSession, property_id: uuid.UUID
) -> Property | None:
    return await db.scalar(select(Property).where(Property.id == property_id))


async def on_bid_placed(db: AsyncSession, bid: Bid) -> None:
    """Notify the property's manager that a new bid landed."""
    prop = await _property_with_manager(db, bid.property_id)
    if prop is None:
        return
    await _notify(
        db,
        user_id=prop.manager_id,
        event="bid_placed",
        audience_role="manager",
        title="New bid",
        body=f"{_money(bid.amount)}/night for {prop.name} — review it.",
        link=f"/manager/properties/{prop.id}/bids",
        related_bid_id=bid.id,
    )
    manager = await db.scalar(select(User).where(User.id == prop.manager_id))
    agent = await db.scalar(select(User).where(User.id == bid.agent_id))
    ctx = {
        "manager_name": manager.full_name if manager else "there",
        "agent_name": agent.full_name if agent else "An agent",
        "property_name": prop.name,
        "amount": _money(bid.amount),
        "check_in": bid.check_in.isoformat(),
        "check_out": bid.check_out.isoformat(),
    }
    await _email(
        db,
        code="bid_placed_manager",
        to=manager.email if manager else None,
        context=ctx,
        link=f"/manager/properties/{prop.id}/bids",
    )
    await _email(
        db,
        code="bid_placed_agent",
        to=agent.email if agent else None,
        context=ctx,
        link="/agent/bids",
    )


async def on_bid_accepted(db: AsyncSession, bid: Bid) -> None:
    """Notify the agent their bid was accepted."""
    prop = await _property_with_manager(db, bid.property_id)
    name = prop.name if prop else "the property"
    await _notify(
        db,
        user_id=bid.agent_id,
        event="bid_accepted",
        audience_role="agent",
        title="Bid accepted",
        body=f"Your bid for {name} was accepted. Collect payment to confirm.",
        link="/agent/bids",
        related_bid_id=bid.id,
    )
    agent = await db.scalar(select(User).where(User.id == bid.agent_id))
    await _email(
        db,
        code="bid_accepted",
        to=agent.email if agent else None,
        context={
            "agent_name": agent.full_name if agent else "there",
            "amount": _money(bid.amount),
            "property_name": name,
            "check_in": bid.check_in.isoformat(),
            "check_out": bid.check_out.isoformat(),
        },
        link="/agent/bids",
    )


async def on_bid_rejected(db: AsyncSession, bid: Bid) -> None:
    prop = await _property_with_manager(db, bid.property_id)
    name = prop.name if prop else "the property"
    await _notify(
        db,
        user_id=bid.agent_id,
        event="bid_rejected",
        audience_role="agent",
        title="Bid declined",
        body=f"Your bid for {name} was declined.",
        link="/agent/bids",
        related_bid_id=bid.id,
    )
    agent = await db.scalar(select(User).where(User.id == bid.agent_id))
    await _email(
        db,
        code="bid_rejected",
        to=agent.email if agent else None,
        context={
            "agent_name": agent.full_name if agent else "there",
            "property_name": name,
            "check_in": bid.check_in.isoformat(),
            "check_out": bid.check_out.isoformat(),
        },
        link="/agent/properties",
    )


async def on_bid_held(db: AsyncSession, bid: Bid) -> None:
    prop = await _property_with_manager(db, bid.property_id)
    name = prop.name if prop else "the property"
    await _notify(
        db,
        user_id=bid.agent_id,
        event="bid_held",
        audience_role="agent",
        title="Bid on hold",
        body=(
            f"Your bid for {name} is on hold — another overlapping bid was "
            "accepted. It will reactivate if that one falls through."
        ),
        link="/agent/bids",
        related_bid_id=bid.id,
    )
    agent = await db.scalar(select(User).where(User.id == bid.agent_id))
    await _email(
        db,
        code="bid_held",
        to=agent.email if agent else None,
        context={
            "agent_name": agent.full_name if agent else "there",
            "property_name": name,
        },
        link="/agent/bids",
    )


async def on_payment_initiated(db: AsyncSession, bid: Bid) -> None:
    """Notify the manager that an agent started payment."""
    prop = await _property_with_manager(db, bid.property_id)
    if prop is None:
        return
    agent = await db.scalar(select(User).where(User.id == bid.agent_id))
    agent_name = agent.full_name if agent else "An agent"
    await _notify(
        db,
        user_id=prop.manager_id,
        event="payment_initiated",
        audience_role="manager",
        title="Payment to confirm",
        body=f"{agent_name} started payment for {prop.name}. Confirm receipt.",
        link=f"/manager/properties/{prop.id}/bids",
        related_bid_id=bid.id,
    )


async def on_payment_confirmed(db: AsyncSession, bid: Bid) -> None:
    """Notify the agent the booking is confirmed."""
    prop = await _property_with_manager(db, bid.property_id)
    name = prop.name if prop else "the property"
    await _notify(
        db,
        user_id=bid.agent_id,
        event="payment_confirmed",
        audience_role="agent",
        title="Booking confirmed",
        body=f"Payment confirmed for {name}. The booking is locked in.",
        link="/agent/bookings",
        related_bid_id=bid.id,
    )
    agent = await db.scalar(select(User).where(User.id == bid.agent_id))
    await _email(
        db,
        code="booking_confirmed",
        to=agent.email if agent else None,
        context={
            "agent_name": agent.full_name if agent else "there",
            "property_name": name,
            "check_in": bid.check_in.isoformat(),
            "check_out": bid.check_out.isoformat(),
        },
        link="/agent/bookings",
    )


async def on_bid_withdrawn(db: AsyncSession, bid: Bid) -> None:
    prop = await _property_with_manager(db, bid.property_id)
    if prop is None:
        return
    agent = await db.scalar(select(User).where(User.id == bid.agent_id))
    agent_name = agent.full_name if agent else "An agent"
    await _notify(
        db,
        user_id=prop.manager_id,
        event="bid_withdrawn",
        audience_role="manager",
        title="Bid withdrawn",
        body=f"{agent_name} withdrew their bid for {prop.name}.",
        link=f"/manager/properties/{prop.id}/bids",
        related_bid_id=bid.id,
    )
    manager = await db.scalar(select(User).where(User.id == prop.manager_id))
    await _email(
        db,
        code="bid_withdrawn",
        to=manager.email if manager else None,
        context={
            "manager_name": manager.full_name if manager else "there",
            "agent_name": agent_name,
            "property_name": prop.name,
            "check_in": bid.check_in.isoformat(),
            "check_out": bid.check_out.isoformat(),
        },
        link=f"/manager/properties/{prop.id}/bids",
    )


async def on_new_message(
    db: AsyncSession,
    *,
    recipient_id: uuid.UUID,
    recipient_role: str,
    sender_name: str,
    bid_id: uuid.UUID,
) -> None:
    """Notify the other party that a chat message landed."""
    link = (
        "/manager/inbox" if recipient_role == "manager" else "/agent/inbox"
    )
    await _notify(
        db,
        user_id=recipient_id,
        event="message",
        audience_role=recipient_role,
        title=f"Message from {sender_name}",
        body="Open Inbox to reply.",
        link=link,
        related_bid_id=bid_id,
    )
