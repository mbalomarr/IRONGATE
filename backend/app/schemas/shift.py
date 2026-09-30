from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models import Shift
from app.schemas.common import LabeledValue, NamedRef
from app.services.geofence import haversine_m


class LocationIn(BaseModel):
    """A GPS fix from the guard's device."""

    latitude: Decimal = Field(ge=-90, le=90)
    longitude: Decimal = Field(ge=-180, le=180)


class SiteOut(BaseModel):
    id: int
    name: str
    address: Optional[str]
    latitude: float
    longitude: float
    geofence_radius_m: int


class ShiftOut(BaseModel):
    id: int
    guard: NamedRef
    contract_id: int
    contract_number: str
    site: SiteOut
    scheduled_start: datetime
    scheduled_end: datetime
    status: LabeledValue
    clock_in_at: Optional[datetime]
    clock_out_at: Optional[datetime]
    last_latitude: Optional[float]
    last_longitude: Optional[float]
    last_location_at: Optional[datetime]
    distance_m: Optional[int] = Field(description="Distance of the last GPS fix from the site centre.")
    inside_geofence: Optional[bool]
    geofence_breach_flag: bool
    breach_active: bool
    breach_minutes: int
    penalty_flagged: bool

    @classmethod
    def from_model(cls, shift: Shift, now: datetime) -> "ShiftOut":
        facility = shift.contract.bid.request.facility
        distance = inside = None
        if shift.last_latitude is not None and shift.last_longitude is not None:
            meters = haversine_m(facility.latitude, facility.longitude, shift.last_latitude, shift.last_longitude)
            distance, inside = int(round(meters)), meters <= facility.geofence_radius_m
        return cls(
            id=shift.id,
            guard=NamedRef(id=shift.guard.id, name=shift.guard.display_name()),
            contract_id=shift.contract_id,
            contract_number=shift.contract.contract_number,
            site=SiteOut(
                id=facility.id,
                name=facility.display_name(),
                address=facility.address,
                latitude=float(facility.latitude),
                longitude=float(facility.longitude),
                geofence_radius_m=facility.geofence_radius_m,
            ),
            scheduled_start=shift.scheduled_start,
            scheduled_end=shift.scheduled_end,
            status=LabeledValue.of("shift_status", shift.status),
            clock_in_at=shift.clock_in_at,
            clock_out_at=shift.clock_out_at,
            last_latitude=float(shift.last_latitude) if shift.last_latitude is not None else None,
            last_longitude=float(shift.last_longitude) if shift.last_longitude is not None else None,
            last_location_at=shift.last_location_at,
            distance_m=distance,
            inside_geofence=inside,
            geofence_breach_flag=shift.geofence_breach_flag,
            breach_active=shift.breach_active_since is not None,
            breach_minutes=shift.breach_minutes(now),
            penalty_flagged=shift.penalty_flagged,
        )


class GuardDutyOut(BaseModel):
    """Everything the guard mobile view needs in one call."""

    server_time: datetime
    clock_in_window_minutes: int
    guard: NamedRef
    shamoos_status: LabeledValue
    current: Optional[ShiftOut]
    upcoming: List[ShiftOut]
