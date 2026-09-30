from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_db, require_permissions
from app.core.exceptions import AppException
from app.core.i18n import enum_label
from app.core.permissions import Permission
from app.models import Guard, ShamoosVerificationLog, User
from app.models.enums import RoleCode, ShamoosStatus
from app.schemas.common import ERROR_RESPONSES, APIResponse, LabeledValue, Page, ok
from app.schemas.shamoos import (
    GuardVerificationOut,
    ShamoosLogOut,
    ShamoosStatsOut,
    ShamoosVerifyRequest,
    ShamoosVerifyResponse,
)
from app.services.shamoos import ShamoosClient, ShamoosUnavailableError, get_shamoos_client, shamoos_health, verify_guard

router = APIRouter(prefix="/shamoos", tags=["Shamoos"], responses=ERROR_RESPONSES)


@router.post("/verify", response_model=APIResponse[ShamoosVerifyResponse], summary="Mock Shamoos API")
def mock_verify(payload: ShamoosVerifyRequest, client: ShamoosClient = Depends(get_shamoos_client)):
    """Stand-in for the external Shamoos service: randomly returns **Verified** or **Rejected** for a National ID."""
    try:
        result = client.verify(payload.national_id)
    except ShamoosUnavailableError:
        raise AppException("shamoos.service_unavailable", 503)
    label = enum_label("shamoos_status", result.status)
    return ok(
        ShamoosVerifyResponse(
            national_id=result.national_id,
            result="Verified" if result.status == ShamoosStatus.VERIFIED else "Rejected",
            result_label=label,
            reference=result.reference,
            checked_at=result.checked_at,
        ),
        "shamoos.verification_complete",
        status=label,
    )


@router.post("/guards/{guard_id}/verify", response_model=APIResponse[GuardVerificationOut])
def verify_roster_guard(
    guard_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions(Permission.SHAMOOS_VERIFY)),
    client: ShamoosClient = Depends(get_shamoos_client),
):
    """HR/Dispatcher runs a Shamoos check on a guard in their roster and stores the result."""
    guard = db.get(Guard, guard_id)
    if guard is None or (user.role.code != RoleCode.SUPER_ADMIN and guard.firm_id != user.firm_id):
        raise AppException("guard.not_found", 404)

    log = verify_guard(db, guard, user, client)
    status_value = LabeledValue.of("shamoos_status", guard.shamoos_status)
    return ok(
        GuardVerificationOut(
            guard_id=guard.id,
            national_id=guard.national_id,
            shamoos_status=status_value,
            reference=guard.shamoos_reference,
            checked_at=guard.shamoos_checked_at,
            latency_ms=log.latency_ms,
        ),
        "shamoos.verification_complete",
        status=status_value.label,
    )


@router.get("/logs", response_model=APIResponse[Page[ShamoosLogOut]])
def shamoos_logs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions(Permission.SHAMOOS_MONITOR)),
):
    """Audit trail of Shamoos calls (national IDs are masked)."""
    total = db.scalar(select(func.count(ShamoosVerificationLog.id))) or 0
    rows = db.scalars(
        select(ShamoosVerificationLog)
        .options(joinedload(ShamoosVerificationLog.guard), joinedload(ShamoosVerificationLog.requested_by))
        .order_by(ShamoosVerificationLog.created_at.desc(), ShamoosVerificationLog.id.desc())
        .limit(limit)
        .offset(offset)
    ).unique().all()
    return ok(Page(items=[ShamoosLogOut.from_model(r) for r in rows], total=total, limit=limit, offset=offset))


@router.get("/stats", response_model=APIResponse[ShamoosStatsOut])
def shamoos_stats(
    window_hours: int = Query(24, ge=1, le=720),
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions(Permission.SHAMOOS_MONITOR)),
):
    """Shamoos API stability for the Operations dashboard."""
    stats = shamoos_health(db, window_hours)
    stats["health"] = LabeledValue.of("service_health", stats["health"])
    return ok(ShamoosStatsOut(**stats))
