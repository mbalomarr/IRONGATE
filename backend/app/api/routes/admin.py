"""Super Admin portal: firm approvals, platform revenue, manual SLA run."""
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_db, require_permissions
from app.core.config import settings
from app.core.exceptions import AppException
from app.core.permissions import Permission
from app.models import Contract, Firm, GuardRequest, Invoice, User
from app.models.base import utcnow
from app.models.enums import ContractStatus, FirmStatus, InvoiceStatus, RequestStatusCode
from app.schemas.admin import FirmOut, FirmRejectIn, RevenueOut, SLARunOut
from app.schemas.billing import SaasMetricsOut
from app.services.saas import platform_metrics
from app.schemas.common import ERROR_RESPONSES, APIResponse, Page, ok
from app.services.sla import run_sla_penalty_check

router = APIRouter(prefix="/admin", tags=["Platform Admin"], responses=ERROR_RESPONSES)


def _get_firm(db: Session, firm_id: int) -> Firm:
    firm = db.get(Firm, firm_id)
    if firm is None:
        raise AppException("firm.not_found", status.HTTP_404_NOT_FOUND)
    return firm


@router.get("/firms", response_model=APIResponse[Page[FirmOut]])
def list_firms(
    firm_status: Optional[FirmStatus] = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions(Permission.FIRM_REVIEW)),
):
    stmt = select(Firm).options(selectinload(Firm.operating_cities), selectinload(Firm.headquarters_city))
    if firm_status is not None:
        stmt = stmt.where(Firm.status == firm_status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Firm.created_at.desc()).limit(limit).offset(offset)).all()
    return ok(Page(items=[FirmOut.from_model(f) for f in rows], total=total, limit=limit, offset=offset))


@router.post("/firms/{firm_id}/approve", response_model=APIResponse[FirmOut])
def approve_firm(
    firm_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_permissions(Permission.FIRM_REVIEW)),
):
    firm = _get_firm(db, firm_id)
    if firm.status == FirmStatus.APPROVED:
        raise AppException("firm.invalid_status_transition", status.HTTP_409_CONFLICT)
    firm.status = FirmStatus.APPROVED
    firm.rejection_reason = None
    firm.reviewed_by_id = admin.id
    firm.reviewed_at = utcnow()
    db.commit()
    return ok(FirmOut.from_model(firm), "firm.approved")


@router.post("/firms/{firm_id}/reject", response_model=APIResponse[FirmOut])
def reject_firm(
    firm_id: int,
    payload: FirmRejectIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require_permissions(Permission.FIRM_REVIEW)),
):
    firm = _get_firm(db, firm_id)
    if firm.status != FirmStatus.PENDING:
        raise AppException("firm.invalid_status_transition", status.HTTP_409_CONFLICT)
    firm.status = FirmStatus.REJECTED
    firm.rejection_reason = payload.reason
    firm.reviewed_by_id = admin.id
    firm.reviewed_at = utcnow()
    db.commit()
    return ok(FirmOut.from_model(firm), "firm.rejected")


@router.get("/revenue", response_model=APIResponse[RevenueOut])
def platform_revenue(
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions(Permission.REVENUE_VIEW)),
):
    zero = Decimal("0.00")
    paid_fee, paid_gmv, paid_count = db.execute(
        select(
            func.coalesce(func.sum(Invoice.platform_fee), 0),
            func.coalesce(func.sum(Invoice.total_due), 0),
            func.count(Invoice.id),
        ).where(Invoice.status == InvoiceStatus.PAID)
    ).one()
    pending_fee = db.scalar(
        select(func.coalesce(func.sum(Invoice.platform_fee), 0)).where(
            Invoice.status.in_([InvoiceStatus.ISSUED, InvoiceStatus.OVERDUE])
        )
    )
    return ok(
        RevenueOut(
            currency=settings.CURRENCY,
            platform_revenue=Decimal(paid_fee or zero),
            pending_revenue=Decimal(pending_fee or zero),
            gross_merchandise_value=Decimal(paid_gmv or zero),
            paid_invoices=paid_count,
            active_contracts=db.scalar(select(func.count(Contract.id)).where(Contract.status == ContractStatus.ACTIVE)) or 0,
            approved_firms=db.scalar(select(func.count(Firm.id)).where(Firm.status == FirmStatus.APPROVED)) or 0,
            open_requests=db.scalar(
                select(func.count(GuardRequest.id)).where(GuardRequest.status_code == RequestStatusCode.OPEN.value)
            ) or 0,
        )
    )


@router.get("/saas-metrics", response_model=APIResponse[SaasMetricsOut])
def saas_metrics(
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions(Permission.REVENUE_VIEW)),
):
    """SaaS + marketplace KPIs: MRR (platform + per-seat fees), tracked guards, marketplace GMV."""
    return ok(SaasMetricsOut(**platform_metrics(db, utcnow())))


@router.post("/sla/run", response_model=APIResponse[SLARunOut])
def run_sla_check(
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions(Permission.SLA_MANAGE)),
):
    """Trigger the SLA penalty scan immediately (it also runs on a background interval)."""
    penalties = run_sla_penalty_check(db)
    return ok(SLARunOut(penalties_created=len(penalties)), "admin.sla_run_complete", count=len(penalties))
