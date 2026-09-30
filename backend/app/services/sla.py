"""Automated SLA penalties.

`run_sla_penalty_check` scans active-contract shifts whose geofence breach exceeds
the contract threshold (default 30 min) and books one penalty per shift onto that
month's draft invoice. It is idempotent: `penalty_flagged` + unique `sla_penalties.shift_id`.
"""
import calendar
import logging
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Contract, Invoice, Shift, SLAPenalty
from app.models.base import utcnow
from app.models.enums import ContractStatus, InvoiceStatus, PenaltyStatus

logger = logging.getLogger(__name__)
CENT = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def month_bounds(day: date) -> Tuple[date, date]:
    last = calendar.monthrange(day.year, day.month)[1]
    return day.replace(day=1), day.replace(day=last)


def prorated_subtotal(contract: Contract, period_start: date, period_end: date) -> Decimal:
    """Share of the contract value falling inside the billing period (by days)."""
    overlap_start = max(contract.start_date, period_start)
    overlap_end = min(contract.end_date, period_end)
    if overlap_end < overlap_start:
        return Decimal("0.00")
    contract_days = (contract.end_date - contract.start_date).days + 1
    period_days = (overlap_end - overlap_start).days + 1
    return _money(Decimal(contract.total_value) * period_days / contract_days)


def recalculate_invoice(invoice: Invoice) -> None:
    penalty_total = sum((p.amount for p in invoice.penalties if p.status == PenaltyStatus.APPLIED), Decimal("0"))
    invoice.penalty_total = _money(penalty_total)
    invoice.total_due = max(_money(invoice.subtotal - invoice.penalty_total), Decimal("0.00"))
    invoice.platform_fee = _money(invoice.subtotal * settings.PLATFORM_COMMISSION_RATE)


def get_or_create_invoice(db: Session, contract: Contract, on_day: date) -> Invoice:
    period_start, period_end = month_bounds(on_day)
    invoice = db.scalar(
        select(Invoice).where(Invoice.contract_id == contract.id, Invoice.period_start == period_start)
    )
    if invoice is None:
        invoice = Invoice(
            contract=contract,
            invoice_number=f"INV-{contract.id:05d}-{period_start:%Y%m}",
            period_start=period_start,
            period_end=period_end,
            subtotal=prorated_subtotal(contract, period_start, period_end),
            penalty_total=Decimal("0.00"),
            status=InvoiceStatus.DRAFT,
        )
        db.add(invoice)
        recalculate_invoice(invoice)
    return invoice


def run_sla_penalty_check(db: Session, now: Optional[datetime] = None) -> List[SLAPenalty]:
    now = now or utcnow()
    shifts = db.scalars(
        select(Shift)
        .join(Contract, Contract.id == Shift.contract_id)
        .where(
            Shift.geofence_breach_flag.is_(True),
            Shift.penalty_flagged.is_(False),
            Contract.status == ContractStatus.ACTIVE,
        )
    ).all()

    created: List[SLAPenalty] = []
    for shift in shifts:
        contract = shift.contract
        threshold = contract.sla_breach_threshold_minutes or settings.SLA_BREACH_THRESHOLD_MINUTES
        minutes = shift.breach_minutes(now)
        if minutes <= threshold:
            continue

        invoice = get_or_create_invoice(db, contract, shift.scheduled_start.date())
        penalty = SLAPenalty(shift=shift, contract=contract, breach_minutes=minutes, amount=Decimal("0.00"))

        if invoice.status == InvoiceStatus.DRAFT:
            cap = _money(invoice.subtotal * Decimal(contract.sla_max_penalty_percent) / 100)
            remaining = max(cap - invoice.penalty_total, Decimal("0.00"))
            penalty.amount = min(_money(contract.sla_penalty_per_breach), remaining)
            penalty.invoice = invoice
            penalty.status = PenaltyStatus.APPLIED if penalty.amount > 0 else PenaltyStatus.WAIVED
            recalculate_invoice(invoice)
        else:
            # Period already invoiced: leave pending for the finance team / next invoice.
            penalty.amount = _money(contract.sla_penalty_per_breach)
            penalty.status = PenaltyStatus.PENDING

        db.add(penalty)
        shift.penalty_flagged = True
        created.append(penalty)
        # TODO: push a geofence-breach notification to the facility's site supervisor(s).
        logger.warning(
            "SLA breach: shift=%s guard=%s contract=%s minutes=%s penalty=%s",
            shift.id, shift.guard_id, contract.id, minutes, penalty.amount,
        )

    db.commit()
    return created
