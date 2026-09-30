from datetime import date, datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.i18n import get_locale
from app.models.base import Base, TimestampMixin, enum_type, utcnow
from app.models.enums import EmploymentStatus, ShamoosCheckResult, ShamoosStatus

if TYPE_CHECKING:
    from app.models.firm import Firm
    from app.models.incident import Incident
    from app.models.lookup import City
    from app.models.shift import Shift
    from app.models.user import User


class Guard(TimestampMixin, Base):
    """A security guard on a firm's roster. `user_id` links the mobile-app login, if any."""

    __tablename__ = "guards"
    __table_args__ = (Index("ix_guards_firm_availability", "firm_id", "shamoos_status", "employment_status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    firm_id: Mapped[int] = mapped_column(ForeignKey("firms.id"), index=True, nullable=False)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), unique=True)
    # Saudi National ID / Iqama. NOTE: PII — encrypt at rest before going to production.
    national_id: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    full_name_ar: Mapped[Optional[str]] = mapped_column(String(150))
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date)
    city_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cities.id"), index=True)
    employment_status: Mapped[EmploymentStatus] = mapped_column(
        enum_type(EmploymentStatus), default=EmploymentStatus.ACTIVE, nullable=False
    )
    shamoos_status: Mapped[ShamoosStatus] = mapped_column(
        enum_type(ShamoosStatus), default=ShamoosStatus.PENDING, index=True, nullable=False
    )
    shamoos_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    shamoos_reference: Mapped[Optional[str]] = mapped_column(String(64))

    firm: Mapped["Firm"] = relationship(back_populates="guards")
    user: Mapped[Optional["User"]] = relationship(back_populates="guard_profile")
    city: Mapped[Optional["City"]] = relationship()
    shifts: Mapped[List["Shift"]] = relationship(back_populates="guard")
    incidents: Mapped[List["Incident"]] = relationship(back_populates="guard")
    shamoos_logs: Mapped[List["ShamoosVerificationLog"]] = relationship(back_populates="guard")

    def display_name(self, locale: Optional[str] = None) -> str:
        if (locale or get_locale()) == "ar" and self.full_name_ar:
            return self.full_name_ar
        return self.full_name


class ShamoosVerificationLog(Base):
    """Audit trail of every Shamoos call — also feeds the Operations API-stability dashboard."""

    __tablename__ = "shamoos_verification_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    guard_id: Mapped[Optional[int]] = mapped_column(ForeignKey("guards.id", ondelete="SET NULL"), index=True)
    national_id: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    requested_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    result: Mapped[ShamoosCheckResult] = mapped_column(enum_type(ShamoosCheckResult), nullable=False)
    reference: Mapped[Optional[str]] = mapped_column(String(64))
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True, nullable=False)

    guard: Mapped[Optional[Guard]] = relationship(back_populates="shamoos_logs")
    requested_by: Mapped[Optional["User"]] = relationship()
