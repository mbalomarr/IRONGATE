from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, enum_type
from app.models.enums import IncidentSeverity, IncidentStatus

if TYPE_CHECKING:
    from app.models.guard import Guard
    from app.models.shift import Shift
    from app.models.user import User


class Incident(TimestampMixin, Base):
    """Reported by a guard from the mobile app; reviewed by the site supervisor."""

    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(primary_key=True)
    guard_id: Mapped[int] = mapped_column(ForeignKey("guards.id"), index=True, nullable=False)
    shift_id: Mapped[Optional[int]] = mapped_column(ForeignKey("shifts.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    severity: Mapped[IncidentSeverity] = mapped_column(enum_type(IncidentSeverity), index=True, nullable=False)
    status: Mapped[IncidentStatus] = mapped_column(enum_type(IncidentStatus), default=IncidentStatus.OPEN, nullable=False)
    latitude: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    longitude: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    reviewed_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    review_notes: Mapped[Optional[str]] = mapped_column(Text)

    guard: Mapped["Guard"] = relationship(back_populates="incidents")
    shift: Mapped[Optional["Shift"]] = relationship(back_populates="incidents")
    reviewed_by: Mapped[Optional["User"]] = relationship()
