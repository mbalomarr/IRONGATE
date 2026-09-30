from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models import Firm
from app.schemas.common import LabeledValue, NamedRef


class FirmOut(BaseModel):
    id: int
    name: str
    moi_license_number: str
    license_expiry_date: date
    commercial_registration: Optional[str]
    headquarters_city: NamedRef
    operating_cities: List[NamedRef]
    total_guards: int
    rating: Optional[Decimal]
    status: LabeledValue
    rejection_reason: Optional[str]
    reviewed_at: Optional[datetime]
    created_at: datetime

    @classmethod
    def from_model(cls, firm: Firm) -> "FirmOut":
        return cls(
            id=firm.id,
            name=firm.display_name(),
            moi_license_number=firm.moi_license_number,
            license_expiry_date=firm.license_expiry_date,
            commercial_registration=firm.commercial_registration,
            headquarters_city=NamedRef(id=firm.headquarters_city.id, name=firm.headquarters_city.localized_name()),
            operating_cities=[NamedRef(id=c.id, name=c.localized_name()) for c in firm.operating_cities],
            total_guards=firm.total_guards,
            rating=firm.rating,
            status=LabeledValue.of("firm_status", firm.status),
            rejection_reason=firm.rejection_reason,
            reviewed_at=firm.reviewed_at,
            created_at=firm.created_at,
        )


class FirmRejectIn(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)


class RevenueOut(BaseModel):
    currency: str
    platform_revenue: Decimal = Field(description="Platform fees on paid invoices.")
    pending_revenue: Decimal = Field(description="Platform fees on issued, unpaid invoices.")
    gross_merchandise_value: Decimal = Field(description="Total paid by clients.")
    paid_invoices: int
    active_contracts: int
    approved_firms: int
    open_requests: int


class SLARunOut(BaseModel):
    penalties_created: int
