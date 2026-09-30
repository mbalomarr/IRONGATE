from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.i18n import get_locale
from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.lookup import City, Sector
    from app.models.request import GuardRequest
    from app.models.user import User


class Facility(TimestampMixin, Base):
    """A client site that needs guards; its coordinates + radius define the geofence."""

    __tablename__ = "facilities"
    __table_args__ = (
        CheckConstraint("latitude BETWEEN -90 AND 90", name="valid_latitude"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="valid_longitude"),
        CheckConstraint("geofence_radius_m > 0", name="positive_geofence_radius"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    name_ar: Mapped[Optional[str]] = mapped_column(String(200))
    sector_id: Mapped[int] = mapped_column(ForeignKey("sectors.id"), index=True, nullable=False)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"), index=True, nullable=False)
    address: Mapped[Optional[str]] = mapped_column(String(500))
    latitude: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    longitude: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    geofence_radius_m: Mapped[int] = mapped_column(Integer, default=150, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    sector: Mapped["Sector"] = relationship()
    city: Mapped["City"] = relationship()
    users: Mapped[List["User"]] = relationship(back_populates="facility")
    requests: Mapped[List["GuardRequest"]] = relationship(back_populates="facility")

    def display_name(self, locale: Optional[str] = None) -> str:
        if (locale or get_locale()) == "ar" and self.name_ar:
            return self.name_ar
        return self.name
