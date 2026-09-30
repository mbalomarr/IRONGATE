from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, enum_type
from app.models.enums import ContractStatus

if TYPE_CHECKING:
    from app.models.bid import Bid
    from app.models.invoice import Invoice, SLAPenalty
    from app.models.shift import Shift
    from app.models.user import User


class Contract(TimestampMixin, Base):
    """Generated when a facility accepts a bid. Firm signs, then facility approves -> ACTIVE.

    Firm / facility are reached through `bid` (bid.firm, bid.request.facility) to keep the schema normalized.
    """

    __tablename__ = "contracts"

    id: Mapped[int] = mapped_column(primary_key=True)
    contract_number: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    bid_id: Mapped[int] = mapped_column(ForeignKey("bids.id"), unique=True, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    total_value: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    # --- SLA terms ---
    sla_breach_threshold_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    sla_penalty_per_breach: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    sla_max_penalty_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("10"), nullable=False)
    # Free-form extra terms, e.g. {"response_time_minutes": 15, "uniform": "...", "replacement_hours": 4}
    sla_details: Mapped[Optional[dict]] = mapped_column(JSON)

    status: Mapped[ContractStatus] = mapped_column(
        enum_type(ContractStatus), default=ContractStatus.PENDING_FIRM_SIGNATURE, index=True, nullable=False
    )
    firm_signed_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    firm_signed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    facility_approved_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    facility_approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    bid: Mapped["Bid"] = relationship(back_populates="contract")
    firm_signed_by: Mapped[Optional["User"]] = relationship(foreign_keys=[firm_signed_by_id])
    facility_approved_by: Mapped[Optional["User"]] = relationship(foreign_keys=[facility_approved_by_id])
    shifts: Mapped[List["Shift"]] = relationship(back_populates="contract")
    invoices: Mapped[List["Invoice"]] = relationship(back_populates="contract")
    penalties: Mapped[List["SLAPenalty"]] = relationship(back_populates="contract")
