from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, enum_type, utcnow
from app.models.enums import InvoiceStatus, PenaltyStatus

if TYPE_CHECKING:
    from app.models.contract import Contract
    from app.models.shift import Shift
    from app.models.user import User


class Invoice(TimestampMixin, Base):
    """Monthly invoice per contract. `total_due = subtotal - penalty_total`; `platform_fee` is Iron Gate's cut."""

    __tablename__ = "invoices"
    __table_args__ = (UniqueConstraint("contract_id", "period_start", name="uq_invoices_contract_period"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_number: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contracts.id"), index=True, nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    penalty_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    platform_fee: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    total_due: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    status: Mapped[InvoiceStatus] = mapped_column(enum_type(InvoiceStatus), default=InvoiceStatus.DRAFT, index=True, nullable=False)
    issued_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    due_date: Mapped[Optional[date]] = mapped_column(Date)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    paid_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))

    contract: Mapped["Contract"] = relationship(back_populates="invoices")
    paid_by: Mapped[Optional["User"]] = relationship()
    penalties: Mapped[List["SLAPenalty"]] = relationship(back_populates="invoice")


class SLAPenalty(Base):
    """One penalty per breached shift (unique shift_id makes the SLA job idempotent)."""

    __tablename__ = "sla_penalties"

    id: Mapped[int] = mapped_column(primary_key=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id"), unique=True, nullable=False)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contracts.id"), index=True, nullable=False)
    invoice_id: Mapped[Optional[int]] = mapped_column(ForeignKey("invoices.id"), index=True)
    breach_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[PenaltyStatus] = mapped_column(enum_type(PenaltyStatus), default=PenaltyStatus.PENDING, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    shift: Mapped["Shift"] = relationship(back_populates="penalty")
    contract: Mapped["Contract"] = relationship(back_populates="penalties")
    invoice: Mapped[Optional[Invoice]] = relationship(back_populates="penalties")
