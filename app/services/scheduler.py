"""Lightweight in-process scheduler for periodic maintenance jobs.

For now we only run lead expiry (hourly). If the job list grows beyond a
couple of items, swap this for APScheduler — keeping it inline for now to
avoid adding a dependency."""
from __future__ import annotations

import asyncio
import logging

from app.core.database import SessionLocal
from app.services.lead_expiry_service import expire_overdue_leads

logger = logging.getLogger("b2cagent.scheduler")

# Run every hour. The query is cheap (indexed on check_in/status) and we
# want overdue leads to clear within roughly the same hour they expire.
LEAD_EXPIRY_INTERVAL_SECONDS = 60 * 60


async def _run_lead_expiry_once() -> None:
    async with SessionLocal() as db:
        try:
            await expire_overdue_leads(db)
        except Exception:  # noqa: BLE001
            logger.exception("lead expiry sweep failed")


async def _lead_expiry_loop() -> None:
    # First run a few seconds after startup so we don't block readiness.
    await asyncio.sleep(15)
    while True:
        await _run_lead_expiry_once()
        await asyncio.sleep(LEAD_EXPIRY_INTERVAL_SECONDS)


_started_tasks: list[asyncio.Task[None]] = []


def start_scheduler() -> None:
    """Spawn the periodic tasks. Idempotent."""
    if _started_tasks:
        return
    loop = asyncio.get_event_loop()
    _started_tasks.append(loop.create_task(_lead_expiry_loop()))
    logger.info("scheduler started: lead expiry every %ds", LEAD_EXPIRY_INTERVAL_SECONDS)


async def stop_scheduler() -> None:
    for t in _started_tasks:
        t.cancel()
    _started_tasks.clear()
