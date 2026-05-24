"""Expire leads whose trip date has passed without converting.

Rules:
- A lead is "expired" when its check_in date is strictly before today AND its
  current status is `draft` or `active` (i.e. never converted to won/booked,
  never explicitly lost).
- When a lead expires we cancel any of its bids that are still in play
  (`pending` or `on_hold`) by setting them to `withdrawn` — `withdrawn` is the
  closest existing terminal state for "agent's customer is gone".
- Accepted bids are left alone; payment may have landed and we don't want to
  unwind a confirmed booking via the cron.

Called by the background scheduler hourly and exposed as a manual admin
endpoint so it can be re-run on demand."""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Bid, BidStatus, Lead, LeadStatus

logger = logging.getLogger("b2cagent.lead_expiry")


async def expire_overdue_leads(
    db: AsyncSession, *, today: date | None = None
) -> dict[str, int]:
    """Run the expiry sweep once. Returns counts for logging/observability."""
    today = today or datetime.now(timezone.utc).date()

    overdue_leads = (
        await db.scalars(
            select(Lead).where(
                Lead.check_in < today,
                Lead.status.in_([LeadStatus.draft, LeadStatus.active]),
            )
        )
    ).all()

    if not overdue_leads:
        return {"leads_expired": 0, "bids_withdrawn": 0}

    lead_ids = [lead.id for lead in overdue_leads]

    bid_result = await db.execute(
        update(Bid)
        .where(
            Bid.lead_id.in_(lead_ids),
            Bid.status.in_([BidStatus.pending, BidStatus.on_hold]),
        )
        .values(status=BidStatus.withdrawn)
        .execution_options(synchronize_session=False)
    )

    for lead in overdue_leads:
        lead.status = LeadStatus.expired

    await db.commit()

    counts = {
        "leads_expired": len(overdue_leads),
        "bids_withdrawn": bid_result.rowcount or 0,
    }
    logger.info("lead expiry sweep: %s", counts)
    return counts
