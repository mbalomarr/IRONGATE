"""Shifts, GPS clock-in/out and geofence pings (guard mobile app + live tracking)."""
from datetime import timedelta

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_db, require_permissions
from app.core.config import settings
from app.core.exceptions import AppException
from app.core.permissions import CLIENT_ROLES, FIRM_ROLES, Permission
from app.models import Bid, Contract, Facility, GuardRequest, Shift, User
from app.models.base import utcnow
from app.models.enums import ShiftStatus
from app.schemas.common import ERROR_RESPONSES, APIResponse, LabeledValue, NamedRef, Page, ok
from app.schemas.shift import GuardDutyOut, LocationIn, ShiftOut
from app.services.geofence import haversine_m, record_location

router = APIRouter(prefix="/shifts", tags=["Shifts & Geofence"], responses=ERROR_RESPONSES)

_LOAD = (
    joinedload(Shift.guard),
    joinedload(Shift.contract).joinedload(Contract.bid).joinedload(Bid.request).joinedload(GuardRequest.facility),
)
_OPEN_STATUSES = (ShiftStatus.SCHEDULED, ShiftStatus.IN_PROGRESS)


def _facility(shift: Shift) -> Facility:
    return shift.contract.bid.request.facility


def _own_shift(db: Session, shift_id: int, user: User) -> Shift:
    shift = db.get(Shift, shift_id, options=_LOAD)
    if shift is None or shift.guard.user_id != user.id:
        raise AppException("shift.not_found", status.HTTP_404_NOT_FOUND)
    return shift


def _apply_fix(shift: Shift, loc: LocationIn, now) -> None:
    shift.last_latitude = loc.latitude
    shift.last_longitude = loc.longitude
    shift.last_location_at = now


@router.get("", response_model=APIResponse[Page[ShiftOut]])
def list_shifts(
    active_only: bool = Query(True, description="Only shifts on duty now or starting within 12 hours."),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(
        require_permissions(
            Permission.GEOFENCE_ALERTS, Permission.SHIFT_ASSIGN, Permission.GUARD_VIEW, Permission.REQUEST_MONITOR, any_of=True
        )
    ),
):
    """Live tracking feed, scoped to the caller's facility / firm (platform staff see all)."""
    now = utcnow()
    stmt = (
        select(Shift)
        .join(Contract, Contract.id == Shift.contract_id)
        .join(Bid, Bid.id == Contract.bid_id)
        .join(GuardRequest, GuardRequest.id == Bid.request_id)
    )
    role = user.role.code
    if role in CLIENT_ROLES:
        stmt = stmt.where(GuardRequest.facility_id == user.facility_id)
    elif role in FIRM_ROLES:
        stmt = stmt.where(Bid.firm_id == user.firm_id)
    if active_only:
        stmt = stmt.where(
            or_(
                Shift.status == ShiftStatus.IN_PROGRESS,
                and_(
                    Shift.status == ShiftStatus.SCHEDULED,
                    Shift.scheduled_end >= now,
                    Shift.scheduled_start <= now + timedelta(hours=12),
                ),
            )
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.options(*_LOAD).order_by(Shift.scheduled_start).limit(limit).offset(offset)).unique().all()
    return ok(Page(items=[ShiftOut.from_model(s, now) for s in rows], total=total, limit=limit, offset=offset))


@router.get("/me", response_model=APIResponse[GuardDutyOut])
def my_duty(
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions(Permission.SHIFT_VIEW_OWN)),
):
    """Guard app home: current (or next) assignment plus upcoming shifts."""
    guard = user.guard_profile
    if guard is None:
        raise AppException("shift.no_guard_profile", status.HTTP_403_FORBIDDEN)
    now = utcnow()
    shifts = db.scalars(
        select(Shift)
        .options(*_LOAD)
        .where(Shift.guard_id == guard.id, Shift.status.in_(_OPEN_STATUSES), Shift.scheduled_end >= now)
        .order_by(Shift.scheduled_start)
        .limit(8)
    ).unique().all()
    in_progress = [s for s in shifts if s.status == ShiftStatus.IN_PROGRESS]
    current = in_progress[0] if in_progress else (shifts[0] if shifts else None)
    upcoming = [s for s in shifts if s is not current]
    return ok(
        GuardDutyOut(
            server_time=now,
            clock_in_window_minutes=settings.CLOCK_IN_EARLY_MINUTES,
            guard=NamedRef(id=guard.id, name=guard.display_name()),
            shamoos_status=LabeledValue.of("shamoos_status", guard.shamoos_status),
            current=ShiftOut.from_model(current, now) if current else None,
            upcoming=[ShiftOut.from_model(s, now) for s in upcoming],
        )
    )


@router.post("/{shift_id}/clock-in", response_model=APIResponse[ShiftOut])
def clock_in(
    shift_id: int,
    loc: LocationIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions(Permission.SHIFT_CLOCK)),
):
    """GPS clock-in. Only allowed inside the site geofence, from 30 min before start until shift end."""
    shift = _own_shift(db, shift_id, user)
    now = utcnow()
    if shift.status != ShiftStatus.SCHEDULED:
        raise AppException("shift.invalid_state", status.HTTP_409_CONFLICT)
    if now < shift.scheduled_start - timedelta(minutes=settings.CLOCK_IN_EARLY_MINUTES):
        raise AppException("shift.too_early", status.HTTP_409_CONFLICT, params={"minutes": settings.CLOCK_IN_EARLY_MINUTES})
    if now > shift.scheduled_end:
        raise AppException("shift.ended", status.HTTP_409_CONFLICT)

    facility = _facility(shift)
    distance = haversine_m(facility.latitude, facility.longitude, loc.latitude, loc.longitude)
    if distance > facility.geofence_radius_m:
        raise AppException(
            "shift.outside_geofence",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            params={"distance": f"{distance:,.0f}", "radius": facility.geofence_radius_m},
        )

    shift.status = ShiftStatus.IN_PROGRESS
    shift.clock_in_at = now
    shift.clock_in_latitude = loc.latitude
    shift.clock_in_longitude = loc.longitude
    record_location(shift, facility, loc.latitude, loc.longitude, now)
    db.commit()
    return ok(ShiftOut.from_model(shift, now), "shift.clocked_in")


@router.post("/{shift_id}/location", response_model=APIResponse[ShiftOut])
def ping_location(
    shift_id: int,
    loc: LocationIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions(Permission.SHIFT_CLOCK)),
):
    """Periodic GPS ping while on duty; opens/closes geofence breaches that feed the SLA job."""
    shift = _own_shift(db, shift_id, user)
    if shift.status != ShiftStatus.IN_PROGRESS:
        raise AppException("shift.invalid_state", status.HTTP_409_CONFLICT)
    now = utcnow()
    new_breach = record_location(shift, _facility(shift), loc.latitude, loc.longitude, now)
    db.commit()
    out = ShiftOut.from_model(shift, now)
    key = "shift.breach_started" if new_breach else ("shift.location_ok" if out.inside_geofence else "shift.still_outside")
    return ok(out, key)


@router.post("/{shift_id}/clock-out", response_model=APIResponse[ShiftOut])
def clock_out(
    shift_id: int,
    loc: LocationIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions(Permission.SHIFT_CLOCK)),
):
    shift = _own_shift(db, shift_id, user)
    if shift.status != ShiftStatus.IN_PROGRESS:
        raise AppException("shift.invalid_state", status.HTTP_409_CONFLICT)
    now = utcnow()
    if shift.breach_active_since is not None:  # close an open breach so its minutes are counted
        shift.breach_total_minutes = shift.breach_minutes(now)
        shift.breach_active_since = None
    _apply_fix(shift, loc, now)
    shift.clock_out_at = now
    shift.clock_out_latitude = loc.latitude
    shift.clock_out_longitude = loc.longitude
    shift.status = ShiftStatus.COMPLETED
    db.commit()
    return ok(ShiftOut.from_model(shift, now), "shift.clocked_out")
