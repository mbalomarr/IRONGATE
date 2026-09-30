"""Shamoos (national security clearance) integration.

`ShamoosClient` is the seam: swap `MockShamoosClient` for a real HTTP client
once API credentials are available — callers only depend on `verify()`.
"""
import logging
import random
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AppException
from app.models import Guard, ShamoosVerificationLog, User
from app.models.base import utcnow
from app.models.enums import ShamoosCheckResult, ShamoosStatus

logger = logging.getLogger(__name__)


class ShamoosUnavailableError(Exception):
    pass


@dataclass
class ShamoosResult:
    national_id: str
    status: ShamoosStatus  # VERIFIED or REJECTED
    reference: str
    checked_at: datetime


class ShamoosClient:
    def verify(self, national_id: str) -> ShamoosResult:  # pragma: no cover - interface
        raise NotImplementedError


class MockShamoosClient(ShamoosClient):
    """Randomly verifies/rejects. Tune via SHAMOOS_MOCK_APPROVAL_RATE / SHAMOOS_MOCK_FAILURE_RATE."""

    def __init__(self, approval_rate: float, failure_rate: float = 0.0, rng: Optional[random.Random] = None) -> None:
        self.approval_rate = approval_rate
        self.failure_rate = failure_rate
        self.rng = rng or random.Random()

    def verify(self, national_id: str) -> ShamoosResult:
        if self.rng.random() < self.failure_rate:
            raise ShamoosUnavailableError("Mock Shamoos outage")
        status = ShamoosStatus.VERIFIED if self.rng.random() < self.approval_rate else ShamoosStatus.REJECTED
        return ShamoosResult(
            national_id=national_id,
            status=status,
            reference=f"SHM-{uuid.uuid4().hex[:12].upper()}",
            checked_at=utcnow(),
        )


def get_shamoos_client() -> ShamoosClient:
    """FastAPI dependency (override in tests for deterministic results)."""
    return MockShamoosClient(settings.SHAMOOS_MOCK_APPROVAL_RATE, settings.SHAMOOS_MOCK_FAILURE_RATE)


def verify_guard(db: Session, guard: Guard, requested_by: Optional[User], client: ShamoosClient) -> ShamoosVerificationLog:
    """Run a Shamoos check for a roster guard, persist the outcome and log the call."""
    started = time.perf_counter()
    try:
        result = client.verify(guard.national_id)
    except ShamoosUnavailableError as exc:
        db.add(
            ShamoosVerificationLog(
                guard_id=guard.id,
                national_id=guard.national_id,
                requested_by_id=requested_by.id if requested_by else None,
                result=ShamoosCheckResult.ERROR,
                latency_ms=int((time.perf_counter() - started) * 1000),
                error_message=str(exc)[:500],
            )
        )
        db.commit()
        logger.warning("Shamoos unavailable for guard %s: %s", guard.id, exc)
        raise AppException("shamoos.service_unavailable", 503) from exc

    guard.shamoos_status = result.status
    guard.shamoos_checked_at = result.checked_at
    guard.shamoos_reference = result.reference
    log = ShamoosVerificationLog(
        guard_id=guard.id,
        national_id=guard.national_id,
        requested_by_id=requested_by.id if requested_by else None,
        result=ShamoosCheckResult(result.status.value),
        reference=result.reference,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
    db.add(log)
    db.commit()
    return log


def shamoos_health(db: Session, window_hours: int = 24) -> Dict[str, Any]:
    """Aggregate recent Shamoos call outcomes for the Operations dashboard."""
    since = utcnow() - timedelta(hours=window_hours)
    rows = db.execute(
        select(ShamoosVerificationLog.result, func.count(), func.avg(ShamoosVerificationLog.latency_ms))
        .where(ShamoosVerificationLog.created_at >= since)
        .group_by(ShamoosVerificationLog.result)
    ).all()
    counts = {result: count for result, count, _ in rows}
    total = sum(counts.values())
    latency_sum = sum(float(avg or 0) * count for _, count, avg in rows)
    errors = counts.get(ShamoosCheckResult.ERROR, 0)
    error_rate = errors / total if total else 0.0

    if total == 0:
        health = "idle"
    elif error_rate >= 0.5:
        health = "down"
    elif error_rate >= 0.1:
        health = "degraded"
    else:
        health = "healthy"

    return {
        "window_hours": window_hours,
        "total_checks": total,
        "verified": counts.get(ShamoosCheckResult.VERIFIED, 0),
        "rejected": counts.get(ShamoosCheckResult.REJECTED, 0),
        "errors": errors,
        "error_rate": round(error_rate, 4),
        "avg_latency_ms": round(latency_sum / total, 1) if total else None,
        "health": health,
    }
