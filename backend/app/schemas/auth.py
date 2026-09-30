from datetime import date, datetime
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models import User
from app.models.enums import Portal, RoleCode
from app.schemas.common import SAUDI_MOBILE_PATTERN, LabeledValue, i18n_error


class RoleOut(BaseModel):
    code: RoleCode
    name: str
    portal: Portal


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    phone: Optional[str]
    role: RoleOut
    firm_id: Optional[int]
    facility_id: Optional[int]
    preferred_locale: str
    is_active: bool
    created_at: datetime

    @classmethod
    def from_model(cls, user: User) -> "UserOut":
        return cls(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            phone=user.phone,
            role=RoleOut(code=user.role.code, name=user.role.localized_name(), portal=user.role.portal),
            firm_id=user.firm_id,
            facility_id=user.facility_id,
            preferred_locale=user.preferred_locale,
            is_active=user.is_active,
            created_at=user.created_at,
        )


class LoginRequest(BaseModel):
    # Plain str: login only needs to match a stored account, not re-validate the address.
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=72)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class OAuthTokenOut(BaseModel):
    """Bare OAuth2 shape expected by Swagger UI's Authorize dialog."""

    access_token: str
    token_type: str = "bearer"


class _AccountIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    full_name: str = Field(min_length=2, max_length=150)
    phone: Optional[str] = Field(default=None, pattern=SAUDI_MOBILE_PATTERN)
    preferred_locale: Literal["en", "ar"] = "en"

    @field_validator("password")
    @classmethod
    def _password_strength(cls, value: str) -> str:
        if not (any(c.isalpha() for c in value) and any(c.isdigit() for c in value)):
            raise i18n_error("auth.weak_password")
        return value


class FirmProfileIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    name_ar: Optional[str] = Field(default=None, max_length=200)
    moi_license_number: str = Field(min_length=4, max_length=50)
    license_expiry_date: date
    commercial_registration: Optional[str] = Field(default=None, pattern=r"^\d{10}$")
    headquarters_city_id: int = Field(ge=1)
    operating_city_ids: List[int] = Field(default_factory=list, max_length=50)
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = Field(default=None, pattern=SAUDI_MOBILE_PATTERN)

    @field_validator("license_expiry_date")
    @classmethod
    def _license_valid(cls, value: date) -> date:
        if value <= date.today():
            raise i18n_error("firm.license_expired")
        return value


class FacilityProfileIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    name_ar: Optional[str] = Field(default=None, max_length=200)
    sector_id: int = Field(ge=1)
    city_id: int = Field(ge=1)
    address: Optional[str] = Field(default=None, max_length=500)
    latitude: Decimal = Field(ge=-90, le=90)
    longitude: Decimal = Field(ge=-180, le=180)
    geofence_radius_m: int = Field(default=150, ge=20, le=5000)


class FirmManagerRegister(_AccountIn):
    firm: FirmProfileIn


class FacilityManagerRegister(_AccountIn):
    facility: FacilityProfileIn


class StaffCreate(_AccountIn):
    role: RoleCode
    guard_id: Optional[int] = Field(default=None, description="Link a roster guard to this mobile-app login.")


class RegistrationOut(BaseModel):
    user: UserOut
    organization_id: int
    organization_status: Optional[LabeledValue] = None
