from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, enum_type
from app.models.enums import BidStatus

if TYPE_CHECKING:
    from app.models.contract import Contract
    from app.models.firm import Firm
    from app.models.request import GuardRequest
    from app.models.user import User


class Bid(TimestampMixin, Base):
    """A firm's offer on a request. `price_per_guard` covers the full request period (SAR)."""

    __tablename__ = "bids"
    __table_args__ = (
        UniqueConstraint("request_id", "firm_id", name="uq_bids_request_firm"),
        CheckConstraint("price_per_guard > 0", name="positive_price"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("guard_requests.id", ondelete="CASCADE"), index=True, nullable=False)
    firm_id: Mapped[int] = mapped_column(ForeignKey("firms.id"), index=True, nullable=False)
    submitted_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    price_per_guard: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[BidStatus] = mapped_column(enum_type(BidStatus), default=BidStatus.SUBMITTED, index=True, nullable=False)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    request: Mapped["GuardRequest"] = relationship(back_populates="bids")
    firm: Mapped["Firm"] = relationship(back_populates="bids")
    submitted_by: Mapped["User"] = relationship()
    contract: Mapped[Optional["Contract"]] = relationship(back_populates="bid")
