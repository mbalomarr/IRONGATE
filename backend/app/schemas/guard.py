from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models import Guard
from app.schemas.common import SAUDI_MOBILE_PATTERN, LabeledValue, NamedRef, validate_national_id


class GuardCreate(BaseModel):
    national_id: str
    full_name: str = Field(min_length=2, max_length=150)
    full_name_ar: Optional[str] = Field(default=None, max_length=150)
    phone: Optional[str] = Field(default=None, pattern=SAUDI_MOBILE_PATTERN)
    date_of_birth: Optional[date] = None
    city_id: int = Field(ge=1)

    _national_id = field_validator("national_id")(validate_national_id)


class GuardOut(BaseModel):
    id: int
    firm_id: int
    national_id: str
    full_name: str
    city: Optional[NamedRef]
    employment_status: LabeledValue
    shamoos_status: LabeledValue
    shamoos_checked_at: Optional[datetime]
    shamoos_reference: Optional[str]
    has_app_account: bool
    created_at: datetime

    @classmethod
    def from_model(cls, guard: Guard) -> "GuardOut":
        return cls(
            id=guard.id,
            firm_id=guard.firm_id,
            national_id=guard.national_id,
            full_name=guard.display_name(),
            city=NamedRef(id=guard.city.id, name=guard.city.localized_name()) if guard.city else None,
            employment_status=LabeledValue.of("employment_status", guard.employment_status),
            shamoos_status=LabeledValue.of("shamoos_status", guard.shamoos_status),
            shamoos_checked_at=guard.shamoos_checked_at,
            shamoos_reference=guard.shamoos_reference,
            has_app_account=guard.user_id is not None,
            created_at=guard.created_at,
        )
