"""Translatable lookup tables (names stored as {"en": ..., "ar": ...} JSON)."""
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TranslatableNameMixin


class Sector(TranslatableNameMixin, Base):
    """Business sector of a facility, e.g. {"en": "Shopping Mall", "ar": "مركز تجاري"}."""

    __tablename__ = "sectors"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class City(TranslatableNameMixin, Base):
    __tablename__ = "cities"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    latitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 7))
    longitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 7))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class RequestStatus(TranslatableNameMixin, Base):
    """Lifecycle states of a guard request; `code` matches `RequestStatusCode`."""

    __tablename__ = "request_statuses"

    code: Mapped[str] = mapped_column(String(30), primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_terminal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
