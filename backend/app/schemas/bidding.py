from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.config import settings
from app.core.i18n import localize
from app.models import Bid, Contract, GuardRequest
from app.schemas.common import LabeledValue, NamedRef, i18n_error


# ---------------------------------------------------------------------------
# Guard requests
# ---------------------------------------------------------------------------
class RequestCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: Optional[str] = Field(default=None, max_length=5000)
    guard_count: int = Field(ge=1, le=500)
    start_date: date
    end_date: date
    daily_hours: int = Field(default=8, ge=1, le=24)
    bidding_deadline: Optional[datetime] = None
    budget_per_guard: Optional[Decimal] = Field(default=None, gt=0, max_digits=12, decimal_places=2)

    @field_validator("bidding_deadline")
    @classmethod
    def _to_naive_utc(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    @model_validator(mode="after")
    def _check_dates(self) -> "RequestCreate":
        if self.start_date < date.today():
            raise i18n_error("request.start_in_past")
        if self.end_date < self.start_date:
            raise i18n_error("request.invalid_dates")
        if self.bidding_deadline and self.bidding_deadline.date() > self.start_date:
            raise i18n_error("request.deadline_after_start")
        return self


class RequestOut(BaseModel):
    id: int
    facility: NamedRef
    city: NamedRef
    sector: NamedRef
    title: str
    description: Optional[str]
    guard_count: int
    start_date: date
    end_date: date
    duration_days: int
    daily_hours: int
    bidding_deadline: Optional[datetime]
    budget_per_guard: Optional[Decimal]
    status: LabeledValue
    bid_count: int = 0
    created_at: datetime

    @classmethod
    def from_model(cls, req: GuardRequest, bid_count: int = 0) -> "RequestOut":
        facility = req.facility
        return cls(
            id=req.id,
            facility=NamedRef(id=facility.id, name=facility.display_name()),
            city=NamedRef(id=facility.city.id, name=facility.city.localized_name()),
            sector=NamedRef(id=facility.sector.id, name=facility.sector.localized_name()),
            title=req.title,
            description=req.description,
            guard_count=req.guard_count,
            start_date=req.start_date,
            end_date=req.end_date,
            duration_days=req.duration_days,
            daily_hours=req.daily_hours,
            bidding_deadline=req.bidding_deadline,
            budget_per_guard=req.budget_per_guard,
            # Label comes from the request_statuses lookup table's JSON column.
            status=LabeledValue(code=req.status_code, label=localize(req.status.name) or req.status_code),
            bid_count=bid_count,
            created_at=req.created_at,
        )


class FirmRecommendationOut(BaseModel):
    firm: NamedRef
    rating: Optional[Decimal]
    verified_guards: int
    available_guards: int
    headquartered_in_city: bool
    score: float


# ---------------------------------------------------------------------------
# Bids
# ---------------------------------------------------------------------------
class BidCreate(BaseModel):
    price_per_guard: Decimal = Field(gt=0, max_digits=12, decimal_places=2, description="SAR per guard for the full period.")
    notes: Optional[str] = Field(default=None, max_length=2000)


class BidOut(BaseModel):
    id: int
    request_id: int
    firm: NamedRef
    firm_rating: Optional[Decimal]
    price_per_guard: Decimal
    total_price: Decimal
    status: LabeledValue
    notes: Optional[str]
    is_lowest: Optional[bool] = None
    request_title: str
    request_status: LabeledValue
    guard_count: int
    created_at: datetime

    @classmethod
    def from_model(cls, bid: Bid, is_lowest: Optional[bool] = None) -> "BidOut":
        request = bid.request
        return cls(
            id=bid.id,
            request_id=bid.request_id,
            request_title=request.title,
            request_status=LabeledValue(code=request.status_code, label=localize(request.status.name) or request.status_code),
            guard_count=request.guard_count,
            firm=NamedRef(id=bid.firm.id, name=bid.firm.display_name()),
            firm_rating=bid.firm.rating,
            price_per_guard=bid.price_per_guard,
            total_price=bid.total_price,
            status=LabeledValue.of("bid_status", bid.status),
            notes=bid.notes,
            is_lowest=is_lowest,
            created_at=bid.created_at,
        )


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------
class ContractTermsIn(BaseModel):
    sla_breach_threshold_minutes: int = Field(default=settings.SLA_BREACH_THRESHOLD_MINUTES, ge=5, le=240)
    sla_penalty_per_breach: Decimal = Field(default=settings.SLA_DEFAULT_PENALTY_AMOUNT, ge=0, max_digits=12, decimal_places=2)
    sla_max_penalty_percent: Decimal = Field(default=settings.SLA_DEFAULT_MAX_PENALTY_PERCENT, ge=0, le=100)
    sla_details: Optional[Dict[str, Any]] = None


class ContractImportIn(BaseModel):
    """Bring Your Own Contract: register an existing off-platform agreement to start tracking immediately."""

    firm_id: int = Field(ge=1)
    external_reference: str = Field(min_length=2, max_length=60)
    title: Optional[str] = Field(default=None, max_length=200)
    start_date: date
    end_date: date
    guard_count: int = Field(ge=1, le=500)
    daily_hours: int = Field(default=12, ge=1, le=24)
    contract_value: Decimal = Field(gt=0, max_digits=14, decimal_places=2, description="Total value of the existing contract (SAR).")

    @model_validator(mode="after")
    def _check_dates(self) -> "ContractImportIn":
        if self.end_date < self.start_date:
            raise i18n_error("request.invalid_dates")
        if self.end_date < date.today():
            raise i18n_error("contract.import_ended")
        return self


class ContractOut(BaseModel):
    id: int
    contract_number: str
    bid_id: int
    request_id: int
    request_title: str
    guard_count: int
    firm: NamedRef
    facility: NamedRef
    start_date: date
    end_date: date
    total_value: Decimal
    sla_breach_threshold_minutes: int
    sla_penalty_per_breach: Decimal
    sla_max_penalty_percent: Decimal
    sla_details: Optional[Dict[str, Any]]
    source: str = Field(description="'marketplace' (won through bidding) or 'imported' (BYOC).")
    external_reference: Optional[str] = None
    status: LabeledValue
    firm_signed_at: Optional[datetime]
    facility_approved_at: Optional[datetime]
    created_at: datetime

    @classmethod
    def from_model(cls, contract: Contract) -> "ContractOut":
        bid = contract.bid
        facility = bid.request.facility
        return cls(
            id=contract.id,
            contract_number=contract.contract_number,
            bid_id=bid.id,
            request_id=bid.request_id,
            request_title=bid.request.title,
            guard_count=bid.request.guard_count,
            firm=NamedRef(id=bid.firm.id, name=bid.firm.display_name()),
            facility=NamedRef(id=facility.id, name=facility.display_name()),
            start_date=contract.start_date,
            end_date=contract.end_date,
            total_value=contract.total_value,
            sla_breach_threshold_minutes=contract.sla_breach_threshold_minutes,
            sla_penalty_per_breach=contract.sla_penalty_per_breach,
            sla_max_penalty_percent=contract.sla_max_penalty_percent,
            sla_details=contract.sla_details,
            source=(contract.sla_details or {}).get("source", "marketplace"),
            external_reference=(contract.sla_details or {}).get("external_reference"),
            status=LabeledValue.of("contract_status", contract.status),
            firm_signed_at=contract.firm_signed_at,
            facility_approved_at=contract.facility_approved_at,
            created_at=contract.created_at,
        )
