"""SaaS subscription maths (per-seat pricing) and platform business metrics.

Pricing: every facility with at least one active contract pays a flat platform fee,
plus a per-seat fee for each distinct guard tracked on its active contracts this month.
Marketplace GMV counts contracts awarded through bidding; imported (BYOC) contracts
are SaaS-only and excluded from GMV.

Billing months are Riyadh calendar months (Asia/Riyadh is UTC+3 all year, no DST);
timestamps in the database are naive UTC.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Bid, Contract, Guard, GuardRequest, Shift
from app.models.enums import BidStatus, ContractStatus, ShiftStatus

CENT = Decimal("0.01")
RIYADH_OFFSET = timedelta(hours=3)
IMPORTED = "imported"
GMV_STATUSES = (
    ContractStatus.PENDING_FIRM_SIGNATURE,
    ContractStatus.PENDING_FACILITY_APPROVAL,
    ContractStatus.ACTIVE,
    ContractStatus.COMPLETED,
)


def is_imported(contract: Contract) -> bool:
    return (contract.sla_details or {}).get("source") == IMPORTED


def riyadh(now: datetime) -> datetime:
    return now + RIYADH_OFFSET


def month_start(now: datetime) -> datetime:
    """Start of the current Riyadh billing month, as naive UTC."""
    local = riyadh(now)
    return datetime(local.year, local.month, 1) - RIYADH_OFFSET


def period_dates(now: datetime):
    local = riyadh(now)
    start = date(local.year, local.month, 1)
    return start, date(local.year + (local.month == 12), local.month % 12 + 1, 1)


def _tracked_guards_stmt(now: datetime, facility_id: Optional[int] = None):
    stmt = (
        select(distinct(Shift.guard_id))
        .join(Contract, Contract.id == Shift.contract_id)
        .join(Bid, Bid.id == Contract.bid_id)
        .join(GuardRequest, GuardRequest.id == Bid.request_id)
        .where(
            Contract.status == ContractStatus.ACTIVE,
            Shift.status != ShiftStatus.CANCELLED,
            Shift.scheduled_end >= month_start(now),
        )
    )
    if facility_id is not None:
        stmt = stmt.where(GuardRequest.facility_id == facility_id)
    return stmt


def _active_contracts(db: Session, facility_id: Optional[int] = None) -> List[Contract]:
    stmt = (
        select(Contract)
        .join(Bid, Bid.id == Contract.bid_id)
        .join(GuardRequest, GuardRequest.id == Bid.request_id)
        .where(Contract.status == ContractStatus.ACTIVE)
    )
    if facility_id is not None:
        stmt = stmt.where(GuardRequest.facility_id == facility_id)
    return list(db.scalars(stmt))


def facility_subscription(db: Session, facility_id: int, now: datetime) -> Dict[str, Any]:
    guard_ids = list(db.scalars(_tracked_guards_stmt(now, facility_id)))
    guards = list(db.scalars(select(Guard).where(Guard.id.in_(guard_ids)).order_by(Guard.id))) if guard_ids else []
    contracts = _active_contracts(db, facility_id)
    platform_fee = settings.SAAS_PLATFORM_FEE
    seat_fee = settings.SAAS_SEAT_FEE
    seats_total = (seat_fee * len(guards)).quantize(CENT)
    active = bool(contracts)
    period_start, period_end = period_dates(now)
    return {
        "active": active,
        "period_start": period_start,
        "period_end": period_end,
        "platform_fee": platform_fee,
        "seat_fee": seat_fee,
        "seats": len(guards),
        "seat_guards": guards,
        "seats_total": seats_total,
        "monthly_total": (platform_fee + seats_total).quantize(CENT) if active else Decimal("0.00"),
        "active_contracts": len(contracts),
        "imported_contracts": sum(1 for c in contracts if is_imported(c)),
    }


def platform_metrics(db: Session, now: datetime, months: int = 6) -> Dict[str, Any]:
    subscribed = set(
        db.scalars(
            select(distinct(GuardRequest.facility_id))
            .join(Bid, Bid.request_id == GuardRequest.id)
            .join(Contract, Contract.bid_id == Bid.id)
            .where(Contract.status == ContractStatus.ACTIVE)
        )
    )
    tracked = len(list(db.scalars(_tracked_guards_stmt(now))))
    platform_fees = (settings.SAAS_PLATFORM_FEE * len(subscribed)).quantize(CENT)
    seat_fees = (settings.SAAS_SEAT_FEE * tracked).quantize(CENT)
    mrr = platform_fees + seat_fees

    contracts = list(db.scalars(select(Contract).where(Contract.status.in_(GMV_STATUSES))))
    marketplace = [c for c in contracts if not is_imported(c)]
    gmv = sum((c.total_value for c in marketplace), Decimal("0"))

    # Last N calendar months of marketplace GMV, oldest first.
    buckets: List[Dict[str, Any]] = []
    local = riyadh(now)
    y, m = local.year, local.month
    for _ in range(months):
        buckets.append({"month": f"{y:04d}-{m:02d}", "value": Decimal("0")})
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    buckets.reverse()
    index = {b["month"]: b for b in buckets}
    for c in marketplace:
        created = riyadh(c.created_at)
        key = f"{created.year:04d}-{created.month:02d}"
        if key in index:
            index[key]["value"] += c.total_value

    open_bids = db.scalar(select(func.coalesce(func.sum(Bid.total_price), 0)).where(Bid.status == BidStatus.SUBMITTED))
    rate = settings.PLATFORM_COMMISSION_RATE
    return {
        "currency": settings.CURRENCY,
        "platform_fee": settings.SAAS_PLATFORM_FEE,
        "seat_fee": settings.SAAS_SEAT_FEE,
        "subscribed_facilities": len(subscribed),
        "tracked_guards": tracked,
        "platform_fees": platform_fees,
        "seat_fees": seat_fees,
        "mrr": mrr.quantize(CENT),
        "arr": (mrr * 12).quantize(CENT),
        "gmv": gmv.quantize(CENT),
        "gmv_this_month": buckets[-1]["value"].quantize(CENT),
        "open_bid_volume": Decimal(open_bids or 0).quantize(CENT),
        "take_rate": float(rate),
        "marketplace_revenue": (gmv * rate).quantize(CENT),
        "marketplace_contracts": len(marketplace),
        "imported_contracts": len(contracts) - len(marketplace),
        "gmv_by_month": [{"month": b["month"], "value": b["value"].quantize(CENT)} for b in buckets],
    }
