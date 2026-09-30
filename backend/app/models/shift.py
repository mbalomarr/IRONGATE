from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, enum_type
from app.models.enums import ShiftStatus

if TYPE_CHECKING:
    from app.models.contract import Contract
    from app.models.guard import Guard
    from app.models.incident import Incident
    from app.models.invoice import SLAPenalty
    from app.models.user import User


class Shift(TimestampMixin, Base):
    """A guard's scheduled shift under a contract, with GPS clock-in/out and geofence tracking.

    Geofence semantics:
      * `geofence_breach_flag` is set the first time the guard leaves the facility radius and stays set.
      * `breach_active_since` is non-null while the guard is currently outside.
      * `breach_total_minutes` accumulates completed breach periods.
    """

    __tablename__ = "shifts"
    __table_args__ = (
        CheckConstraint("scheduled_end > scheduled_start", name="valid_schedule"),
        Index("ix_shifts_guard_schedule", "guard_id", "scheduled_start"),
        Index("ix_shifts_breach_scan", "geofence_breach_flag", "penalty_flagged"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    guard_id: Mapped[int] = mapped_column(ForeignKey("guards.id"), nullable=False)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contracts.id"), index=True, nullable=False)
    assigned_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    scheduled_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    scheduled_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[ShiftStatus] = mapped_column(enum_type(ShiftStatus), default=ShiftStatus.SCHEDULED, nullable=False)

    clock_in_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    clock_in_latitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 7))
    clock_in_longitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 7))
    clock_out_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    clock_out_latitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 7))
    clock_out_longitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 7))

    last_latitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 7))
    last_longitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 7))
    last_location_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    geofence_breach_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    breach_active_since: Mapped[Optional[datetime]] = mapped_column(DateTime)
    breach_total_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    penalty_flagged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    guard: Mapped["Guard"] = relationship(back_populates="shifts")
    contract: Mapped["Contract"] = relationship(back_populates="shifts")
    assigned_by: Mapped[Optional["User"]] = relationship()
    incidents: Mapped[List["Incident"]] = relationship(back_populates="shift")
    penalty: Mapped[Optional["SLAPenalty"]] = relationship(back_populates="shift")

    def breach_minutes(self, now: datetime) -> int:
        """Total minutes spent outside the geofence, including an ongoing breach."""
        minutes = self.breach_total_minutes or 0
        if self.breach_active_since is not None:
            minutes += int((now - self.breach_active_since).total_seconds() // 60)
        return minutes
