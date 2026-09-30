from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import RequestStatusCode

if TYPE_CHECKING:
    from app.models.bid import Bid
    from app.models.facility import Facility
    from app.models.lookup import RequestStatus
    from app.models.user import User


class GuardRequest(TimestampMixin, Base):
    """A facility's request for N guards over a period; firms bid on it."""

    __tablename__ = "guard_requests"
    __table_args__ = (
        CheckConstraint("guard_count > 0", name="positive_guard_count"),
        CheckConstraint("end_date >= start_date", name="valid_period"),
        CheckConstraint("daily_hours BETWEEN 1 AND 24", name="valid_daily_hours"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id"), index=True, nullable=False)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    guard_count: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    daily_hours: Mapped[int] = mapped_column(Integer, default=8, nullable=False)
    bidding_deadline: Mapped[Optional[datetime]] = mapped_column(DateTime)
    budget_per_guard: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    status_code: Mapped[str] = mapped_column(
        ForeignKey("request_statuses.code"), default=RequestStatusCode.OPEN.value, index=True, nullable=False
    )

    facility: Mapped["Facility"] = relationship(back_populates="requests")
    created_by: Mapped["User"] = relationship()
    status: Mapped["RequestStatus"] = relationship(lazy="joined")
    bids: Mapped[List["Bid"]] = relationship(back_populates="request", cascade="all, delete-orphan")

    @property
    def duration_days(self) -> int:
        return (self.end_date - self.start_date).days + 1
