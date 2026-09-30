"""GPS geofencing helpers used by guard location pings (clock-in / periodic updates)."""
import math
from datetime import datetime
from decimal import Decimal
from typing import Union

from app.models import Facility, Shift

Number = Union[float, Decimal]
EARTH_RADIUS_M = 6_371_000


def haversine_m(lat1: Number, lon1: Number, lat2: Number, lon2: Number) -> float:
    phi1, phi2 = math.radians(float(lat1)), math.radians(float(lat2))
    d_phi = math.radians(float(lat2) - float(lat1))
    d_lambda = math.radians(float(lon2) - float(lon1))
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def is_inside_geofence(facility: Facility, latitude: Number, longitude: Number) -> bool:
    return haversine_m(facility.latitude, facility.longitude, latitude, longitude) <= facility.geofence_radius_m


def record_location(shift: Shift, facility: Facility, latitude: Number, longitude: Number, now: datetime) -> bool:
    """Update the shift's breach tracking from a GPS ping.

    Returns True when a *new* breach starts (caller should alert the site supervisor).
    """
    shift.last_latitude = Decimal(str(latitude))
    shift.last_longitude = Decimal(str(longitude))
    shift.last_location_at = now

    inside = is_inside_geofence(facility, latitude, longitude)
    if not inside and shift.breach_active_since is None:
        shift.geofence_breach_flag = True
        shift.breach_active_since = now
        return True
    if inside and shift.breach_active_since is not None:
        elapsed = int((now - shift.breach_active_since).total_seconds() // 60)
        shift.breach_total_minutes = (shift.breach_total_minutes or 0) + elapsed
        shift.breach_active_since = None
    return False
