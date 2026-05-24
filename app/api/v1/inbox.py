"""Inbox API: notifications + bid-thread messages."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.sql import ColumnElement
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import get_current_user
from app.models import (
    Bid,
    BidMessage,
    Notification,
    Property,
    User,
)
from app.schemas.inbox import (
    MessageCreateIn,
    MessageOut,
    NotificationOut,
    ThreadOut,
    UnreadCountOut,
)
from app.services.notification_service import on_new_message

router = APIRouter(prefix="/inbox", tags=["inbox"])


def _audience_filter(user: User) -> ColumnElement[bool]:
    """A notification is visible to the user when its audience matches the
    user's active role, OR when the audience is NULL (role-agnostic)."""
    role = user.active_role.value if user.active_role else None
    if role in ("manager", "agent"):
        return or_(
            Notification.audience_role == role,
            Notification.audience_role.is_(None),
        )
    # Admin / unset → see everything.
    return Notification.id == Notification.id  # always-true


# ---------------- Notifications ----------------


@router.get("/notifications", response_model=list[NotificationOut])
async def list_notifications(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    limit: int = Query(default=100, ge=1, le=200),
) -> list[Notification]:
    rows = (
        await db.scalars(
            select(Notification)
            .where(Notification.user_id == user.id, _audience_filter(user))
            .order_by(Notification.created_at.desc())
            .limit(limit)
        )
    ).all()
    # Fallback: if the role-filtered view is empty, return everything the user
    # has so they're never staring at an empty inbox when data exists.
    if not rows:
        rows = (
            await db.scalars(
                select(Notification)
                .where(Notification.user_id == user.id)
                .order_by(Notification.created_at.desc())
                .limit(limit)
            )
        ).all()
    return list(rows)


@router.get("/unread-count", response_model=UnreadCountOut)
async def unread_count(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UnreadCountOut:
    n = await db.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == user.id,
            Notification.read_at.is_(None),
            _audience_filter(user),
        )
    )
    # Same fallback as the list endpoint: if nothing matches the role filter
    # but the user has other unread items, surface their total count instead.
    if not n:
        n = await db.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == user.id,
                Notification.read_at.is_(None),
            )
        )
    # Unread messages = messages on bids where I'm participant, sent by other party, unread.
    m = await db.scalar(
        select(func.count(BidMessage.id))
        .join(Bid, BidMessage.bid_id == Bid.id)
        .join(Property, Bid.property_id == Property.id)
        .where(
            BidMessage.sender_id != user.id,
            BidMessage.read_at.is_(None),
            or_(
                Bid.agent_id == user.id,
                Property.manager_id == user.id,
            ),
        )
    )
    return UnreadCountOut(notifications=int(n or 0), messages=int(m or 0))


@router.patch("/notifications/{notification_id}/read")
async def mark_read(
    notification_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    n = await db.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user.id,
        )
    )
    if n is None:
        raise HTTPException(status_code=404, detail="notification not found")
    if n.read_at is None:
        n.read_at = datetime.now(timezone.utc)
        await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/notifications/mark-all-read")
async def mark_all_read(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    now = datetime.now(timezone.utc)
    rows = (
        await db.scalars(
            select(Notification).where(
                Notification.user_id == user.id,
                Notification.read_at.is_(None),
                _audience_filter(user),
            )
        )
    ).all()
    for r in rows:
        r.read_at = now
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------- Threads / messages ----------------


async def _ensure_participant(
    db: AsyncSession, bid_id: uuid.UUID, user: User
) -> tuple[Bid, Property]:
    """Confirm the user is either the bid's agent or the property's manager."""
    bid = await db.scalar(select(Bid).where(Bid.id == bid_id))
    if bid is None:
        raise HTTPException(status_code=404, detail="bid not found")
    prop = await db.scalar(select(Property).where(Property.id == bid.property_id))
    if prop is None:
        raise HTTPException(status_code=404, detail="property not found")
    if user.id not in (bid.agent_id, prop.manager_id):
        raise HTTPException(status_code=403, detail="not a participant")
    return bid, prop


@router.get("/threads", response_model=list[ThreadOut])
async def list_threads(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ThreadOut]:
    """Return every bid-thread this user is a participant in, with a
    last-message preview and per-thread unread count."""
    bids = (
        await db.scalars(
            select(Bid)
            .join(Property, Bid.property_id == Property.id)
            .options(selectinload(Bid.agent), selectinload(Bid.property))
            .where(
                or_(
                    Bid.agent_id == user.id,
                    Property.manager_id == user.id,
                )
            )
            .order_by(Bid.created_at.desc())
        )
    ).all()

    out: list[ThreadOut] = []
    for b in bids:
        last_msg = await db.scalar(
            select(BidMessage)
            .where(BidMessage.bid_id == b.id)
            .order_by(BidMessage.created_at.desc())
            .limit(1)
        )
        unread = await db.scalar(
            select(func.count(BidMessage.id)).where(
                BidMessage.bid_id == b.id,
                BidMessage.sender_id != user.id,
                BidMessage.read_at.is_(None),
            )
        )
        # Other party = the participant who isn't `user`.
        if user.id == b.agent_id:
            other = await db.scalar(
                select(User).where(User.id == b.property.manager_id)
            )
        else:
            other = b.agent
        if other is None:
            continue
        # Skip threads with no messages AND no activity worth surfacing.
        # Keep them anyway so users can start a conversation from any bid.
        out.append(
            ThreadOut(
                bid_id=b.id,
                property_id=b.property_id,
                property_name=b.property.name,
                other_party_id=other.id,
                other_party_name=other.full_name,
                last_message=last_msg.body if last_msg else None,
                last_message_at=last_msg.created_at if last_msg else None,
                unread_count=int(unread or 0),
                bid_status=b.status.value,
                bid_check_in=b.check_in.isoformat(),
                bid_check_out=b.check_out.isoformat(),
            )
        )
    # Sort: threads with messages first (by last_message_at desc), then the rest
    # by bid creation order (already preserved from the SQL).
    out.sort(
        key=lambda t: (
            0 if t.last_message_at is not None else 1,
            -(t.last_message_at.timestamp() if t.last_message_at else 0),
        )
    )
    return out


@router.get("/threads/{bid_id}/messages", response_model=list[MessageOut])
async def list_messages(
    bid_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[MessageOut]:
    await _ensure_participant(db, bid_id, user)
    rows = (
        await db.execute(
            select(BidMessage, User.full_name)
            .join(User, BidMessage.sender_id == User.id)
            .where(BidMessage.bid_id == bid_id)
            .order_by(BidMessage.created_at.asc())
        )
    ).all()
    # Mark unread messages from the other party as read.
    now = datetime.now(timezone.utc)
    for m, _ in rows:
        if m.sender_id != user.id and m.read_at is None:
            m.read_at = now
    await db.commit()

    return [
        MessageOut(
            id=m.id,
            bid_id=m.bid_id,
            sender_id=m.sender_id,
            sender_name=name,
            body=m.body,
            read_at=m.read_at,
            created_at=m.created_at,
        )
        for m, name in rows
    ]


@router.post("/threads/{bid_id}/messages", response_model=MessageOut)
async def post_message(
    bid_id: uuid.UUID,
    payload: MessageCreateIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MessageOut:
    bid, prop = await _ensure_participant(db, bid_id, user)
    msg = BidMessage(bid_id=bid.id, sender_id=user.id, body=payload.body)
    db.add(msg)
    # Notify the other party — audience role = the recipient's side of the bid.
    if user.id == bid.agent_id:
        recipient_id = prop.manager_id
        recipient_role = "manager"
    else:
        recipient_id = bid.agent_id
        recipient_role = "agent"
    await on_new_message(
        db,
        recipient_id=recipient_id,
        recipient_role=recipient_role,
        sender_name=user.full_name,
        bid_id=bid.id,
    )
    await db.commit()
    await db.refresh(msg)
    return MessageOut(
        id=msg.id,
        bid_id=msg.bid_id,
        sender_id=msg.sender_id,
        sender_name=user.full_name,
        body=msg.body,
        read_at=msg.read_at,
        created_at=msg.created_at,
    )
