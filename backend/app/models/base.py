"""Declarative base, shared mixins and column helpers."""
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Type

from sqlalchemy import JSON, DateTime, MetaData
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.i18n import localize

# Deterministic constraint names keep Alembic diffs stable (and fit MySQL's 64-char limit).
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    """Naive UTC timestamp — MySQL DATETIME has no timezone, so everything is stored as UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def enum_type(enum_cls: Type[Enum]) -> SAEnum:
    """Persist a Python Enum by its `.value` (native ENUM on MySQL)."""
    return SAEnum(
        enum_cls,
        name=re.sub(r"(?<!^)(?=[A-Z])", "_", enum_cls.__name__).lower(),
        values_callable=lambda members: [m.value for m in members],
        validate_strings=True,
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class TranslatableNameMixin:
    """Lookup rows keep their display name as JSON: {"en": "Shopping Mall", "ar": "مركز تجاري"}."""

    name: Mapped[dict] = mapped_column(JSON, nullable=False)

    def localized_name(self, locale: Optional[str] = None) -> str:
        return localize(self.name, locale) or ""
