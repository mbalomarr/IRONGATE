from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, field_validator

from app.models import ShamoosVerificationLog
from app.schemas.common import LabeledValue, validate_national_id


def mask_national_id(value: str) -> str:
    return value[:2] + "•" * 5 + value[-3:] if len(value) == 10 else value


class ShamoosVerifyRequest(BaseModel):
    national_id: str

    _national_id = field_validator("national_id")(validate_national_id)


class ShamoosVerifyResponse(BaseModel):
    """Shape of the (mock) external Shamoos API."""

    national_id: str
    result: Literal["Verified", "Rejected"]
    result_label: str
    reference: str
    checked_at: datetime


class GuardVerificationOut(BaseModel):
    guard_id: int
    national_id: str
    shamoos_status: LabeledValue
    reference: Optional[str]
    checked_at: Optional[datetime]
    latency_ms: int


class ShamoosLogOut(BaseModel):
    id: int
    national_id: str
    guard_name: Optional[str]
    result: LabeledValue
    reference: Optional[str]
    latency_ms: int
    requested_by: Optional[str]
    created_at: datetime

    @classmethod
    def from_model(cls, log: ShamoosVerificationLog) -> "ShamoosLogOut":
        return cls(
            id=log.id,
            national_id=mask_national_id(log.national_id),
            guard_name=log.guard.display_name() if log.guard else None,
            result=LabeledValue.of("shamoos_result", log.result),
            reference=log.reference,
            latency_ms=log.latency_ms,
            requested_by=log.requested_by.full_name if log.requested_by else None,
            created_at=log.created_at,
        )


class ShamoosStatsOut(BaseModel):
    window_hours: int
    total_checks: int
    verified: int
    rejected: int
    errors: int
    error_rate: float
    avg_latency_ms: Optional[float]
    health: LabeledValue
