from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.i18n import get_locale
from app.models.base import Base, TimestampMixin, enum_type
from app.models.enums import FirmStatus

if TYPE_CHECKING:
    from app.models.bid import Bid
    from app.models.guard import Guard
    from app.models.lookup import City
    from app.models.user import User

# Cities a firm is licensed / willing to deploy guards in (used by smart matching).
firm_cities = Table(
    "firm_cities",
    Base.metadata,
    Column("firm_id", ForeignKey("firms.id", ondelete="CASCADE"), primary_key=True),
    Column("city_id", ForeignKey("cities.id", ondelete="CASCADE"), primary_key=True),
)


class Firm(TimestampMixin, Base):
    """MOI-licensed security company."""

    __tablename__ = "firms"
    __table_args__ = (CheckConstraint("total_guards >= 0", name="total_guards_non_negative"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    name_ar: Mapped[Optional[str]] = mapped_column(String(200))
    moi_license_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    license_expiry_date: Mapped[date] = mapped_column(Date, nullable=False)
    commercial_registration: Mapped[Optional[str]] = mapped_column(String(20), unique=True)
    headquarters_city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"), index=True, nullable=False)
    contact_email: Mapped[Optional[str]] = mapped_column(String(255))
    contact_phone: Mapped[Optional[str]] = mapped_column(String(20))
    # Denormalized roster size (non-terminated guards); kept in sync by the guards service.
    total_guards: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rating: Mapped[Optional[Decimal]] = mapped_column(Numeric(3, 2))
    status: Mapped[FirmStatus] = mapped_column(enum_type(FirmStatus), default=FirmStatus.PENDING, index=True, nullable=False)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text)
    # use_alter breaks the users <-> firms FK cycle during CREATE TABLE.
    reviewed_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", use_alter=True))
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    headquarters_city: Mapped["City"] = relationship()
    operating_cities: Mapped[List["City"]] = relationship(secondary=firm_cities)
    users: Mapped[List["User"]] = relationship(back_populates="firm", foreign_keys="User.firm_id")
    reviewed_by: Mapped[Optional["User"]] = relationship(foreign_keys=[reviewed_by_id])
    guards: Mapped[List["Guard"]] = relationship(back_populates="firm")
    bids: Mapped[List["Bid"]] = relationship(back_populates="firm")

    def display_name(self, locale: Optional[str] = None) -> str:
        if (locale or get_locale()) == "ar" and self.name_ar:
            return self.name_ar
        return self.name
