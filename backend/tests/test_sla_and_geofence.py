from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.models import Bid, Contract, Facility, Firm, Guard, GuardRequest, Invoice, Role, Shift, SLAPenalty, User
from app.models.enums import ContractStatus, FirmStatus, PenaltyStatus, RoleCode
from app.services.geofence import haversine_m, record_location
from app.services.sla import run_sla_penalty_check


def _active_contract(db, city_ids, sector_ids):
    role = db.scalar(select(Role).where(Role.code == RoleCode.FACILITY_MANAGER))
    firm = Firm(
        name="Shield",
        moi_license_number="MOI-1",
        license_expiry_date=date(2030, 1, 1),
        headquarters_city_id=city_ids["riyadh"],
        status=FirmStatus.APPROVED,
    )
    facility = Facility(
        name="Mall",
        sector_id=sector_ids["shopping_mall"],
        city_id=city_ids["riyadh"],
        latitude=Decimal("24.7560"),
        longitude=Decimal("46.6290"),
        geofence_radius_m=200,
    )
    user = User(email="fm@x.sa", full_name="FM", hashed_password="x", role=role, facility=facility)
    req = GuardRequest(
        facility=facility, created_by=user, title="T", guard_count=1,
        start_date=date(2026, 10, 1), end_date=date(2026, 10, 31),
    )
    bid = Bid(request=req, firm=firm, submitted_by=user, price_per_guard=Decimal("31000"), total_price=Decimal("31000"))
    contract = Contract(
        bid=bid, contract_number="IG-TEST", start_date=req.start_date, end_date=req.end_date,
        total_value=Decimal("31000"), status=ContractStatus.ACTIVE,
        sla_breach_threshold_minutes=30, sla_penalty_per_breach=Decimal("500"), sla_max_penalty_percent=Decimal("10"),
    )
    guard = Guard(firm=firm, national_id="1000000001", full_name="G")
    db.add_all([firm, facility, user, req, bid, contract, guard])
    db.commit()
    return contract, guard, facility


def test_haversine():
    # Riyadh -> Jeddah is ~850 km
    assert 840_000 < haversine_m(24.7136, 46.6753, 21.4858, 39.1925) < 860_000


def test_geofence_tracking(db, city_ids, sector_ids):
    contract, guard, facility = _active_contract(db, city_ids, sector_ids)
    t0 = datetime(2026, 10, 5, 8, 0)
    shift = Shift(guard=guard, contract=contract, scheduled_start=t0, scheduled_end=t0 + timedelta(hours=8))

    assert record_location(shift, facility, 24.7561, 46.6291, t0) is False  # inside
    assert record_location(shift, facility, 24.7700, 46.6290, t0 + timedelta(minutes=10)) is True  # ~1.5 km away
    assert shift.geofence_breach_flag is True
    record_location(shift, facility, 24.7560, 46.6290, t0 + timedelta(minutes=30))  # back inside
    assert shift.breach_total_minutes == 20 and shift.breach_active_since is None
    assert shift.geofence_breach_flag is True  # stays flagged for SLA review


def test_sla_penalty_job(db, city_ids, sector_ids):
    contract, guard, _ = _active_contract(db, city_ids, sector_ids)
    now = datetime(2026, 10, 5, 12, 0)
    long_breach = Shift(
        guard=guard, contract=contract, scheduled_start=datetime(2026, 10, 5, 8), scheduled_end=datetime(2026, 10, 5, 16),
        geofence_breach_flag=True, breach_active_since=now - timedelta(minutes=45),
    )
    short_breach = Shift(
        guard=guard, contract=contract, scheduled_start=datetime(2026, 10, 6, 8), scheduled_end=datetime(2026, 10, 6, 16),
        geofence_breach_flag=True, breach_total_minutes=20,
    )
    db.add_all([long_breach, short_breach])
    db.commit()

    penalties = run_sla_penalty_check(db, now=now)
    assert len(penalties) == 1
    penalty = penalties[0]
    assert penalty.shift_id == long_breach.id
    assert penalty.status == PenaltyStatus.APPLIED
    assert penalty.amount == Decimal("500.00")

    invoice = db.scalar(select(Invoice))
    assert invoice.subtotal == Decimal("31000.00")  # whole contract falls in October
    assert invoice.penalty_total == Decimal("500.00")
    assert invoice.total_due == Decimal("30500.00")
    assert invoice.platform_fee == Decimal("3100.00")

    # Idempotent
    assert run_sla_penalty_check(db, now=now + timedelta(hours=1)) == []
    assert len(db.scalars(select(SLAPenalty)).all()) == 1
