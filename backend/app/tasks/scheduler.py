"""In-process background scheduler for periodic jobs.

Placeholder for a real scheduler (Celery beat / APScheduler / cron). With several
uvicorn workers every worker runs this loop; that is safe (the SLA job is idempotent)
but wasteful — in production run it in exactly one process.
"""
import asyncio
import logging

from app.db.session import SessionLocal
from app.services.sla import run_sla_penalty_check

logger = logging.getLogger(__name__)


def _run_sla_check_once() -> int:
    with SessionLocal() as db:
        return len(run_sla_penalty_check(db))


async def sla_penalty_loop(interval_seconds: int) -> None:
    while True:
        try:
            created = await asyncio.to_thread(_run_sla_check_once)
            if created:
                logger.info("SLA job created %s penalties", created)
        except Exception:  # keep the loop alive through DB hiccups
            logger.exception("SLA penalty job failed")
        await asyncio.sleep(interval_seconds)
