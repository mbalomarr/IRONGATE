from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, TranslatableNameMixin, enum_type
from app.models.enums import Portal, RoleCode

if TYPE_CHECKING:
    from app.models.facility import Facility
    from app.models.firm import Firm
    from app.models.guard import Guard


class Role(TranslatableNameMixin, Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[RoleCode] = mapped_column(enum_type(RoleCode), unique=True, nullable=False)
    portal: Mapped[Portal] = mapped_column(enum_type(Portal), nullable=False)
    description: Mapped[Optional[dict]] = mapped_column(JSON)

    users: Mapped[List["User"]] = relationship(back_populates="role")


class User(TimestampMixin, Base):
    """A platform account. Firm staff carry `firm_id`, client staff carry `facility_id`, platform staff neither."""

    __tablename__ = "users"
    __table_args__ = (CheckConstraint("firm_id IS NULL OR facility_id IS NULL", name="single_organization"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), index=True, nullable=False)
    firm_id: Mapped[Optional[int]] = mapped_column(ForeignKey("firms.id"), index=True)
    facility_id: Mapped[Optional[int]] = mapped_column(ForeignKey("facilities.id"), index=True)
    preferred_locale: Mapped[str] = mapped_column(String(5), default="en", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    role: Mapped[Role] = relationship(back_populates="users", lazy="joined")
    firm: Mapped[Optional["Firm"]] = relationship(back_populates="users", foreign_keys=[firm_id])
    facility: Mapped[Optional["Facility"]] = relationship(back_populates="users")
    guard_profile: Mapped[Optional["Guard"]] = relationship(back_populates="user")

    @property
    def role_code(self) -> RoleCode:
        return self.role.code
