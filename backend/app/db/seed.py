"""Idempotent seeding: reference data, super admin and a demo scenario.

Usage:  python -m app.db.seed

Re-running is safe. Lookup names are refreshed from this file, existing accounts are
left untouched, and the demo guard's shifts are re-centred on "now" so the guard app
always has a live assignment to clock into.
"""
import logging
import random
from datetime import date, datetime, timedelta
from decimal import Decimal
from math import cos, radians
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.models import (
    Bid,
    City,
    Contract,
    Facility,
    Firm,
    Guard,
    GuardRequest,
    RequestStatus,
    Role,
    Sector,
    ShamoosVerificationLog,
    Shift,
    User,
)
from app.models.base import utcnow
from app.services.saas import month_start, riyadh
from app.models.enums import (
    BidStatus,
    ContractStatus,
    FirmStatus,
    Portal,
    RequestStatusCode,
    RoleCode,
    ShamoosCheckResult,
    ShamoosStatus,
    ShiftStatus,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Reference data (names are upserted, so terminology fixes propagate on re-seed)
# ---------------------------------------------------------------------------
ROLES = [
    (RoleCode.SUPER_ADMIN, Portal.PLATFORM, {"en": "Super Admin", "ar": "مدير النظام"}),
    (RoleCode.OPERATIONS, Portal.PLATFORM, {"en": "Operations", "ar": "فريق العمليات"}),
    (RoleCode.FIRM_MANAGER, Portal.FIRM, {"en": "Security Firm Manager", "ar": "مدير شركة الحراسات"}),
    (RoleCode.HR_DISPATCHER, Portal.FIRM, {"en": "HR & Dispatch", "ar": "الموارد البشرية والتشغيل"}),
    (RoleCode.FACILITY_MANAGER, Portal.CLIENT, {"en": "Facility Manager", "ar": "مدير المنشأة"}),
    (RoleCode.SITE_SUPERVISOR, Portal.CLIENT, {"en": "Site Supervisor", "ar": "مشرف الموقع"}),
    (RoleCode.SECURITY_GUARD, Portal.MOBILE, {"en": "Security Guard", "ar": "حارس أمن"}),
]

REQUEST_STATUSES = [
    ("open", 10, False, {"en": "Open for Bids", "ar": "مطروح لعروض الأسعار"}),
    ("awarded", 20, False, {"en": "Awarded", "ar": "تمت الترسية"}),
    ("active", 30, False, {"en": "Active", "ar": "ساري"}),
    ("completed", 40, True, {"en": "Completed", "ar": "مكتمل"}),
    ("cancelled", 50, True, {"en": "Cancelled", "ar": "ملغى"}),
]

SECTORS = [
    ("shopping_mall", {"en": "Shopping Mall", "ar": "مركز تجاري"}),
    ("hospital", {"en": "Hospital", "ar": "مستشفى"}),
    ("hotel", {"en": "Hotel", "ar": "فندق"}),
    ("residential_compound", {"en": "Residential Compound", "ar": "مجمع سكني"}),
    ("corporate_office", {"en": "Corporate Office", "ar": "مقر شركة"}),
    ("industrial", {"en": "Industrial Facility", "ar": "منشأة صناعية"}),
    ("bank", {"en": "Bank", "ar": "بنك"}),
    ("education", {"en": "Educational Institution", "ar": "منشأة تعليمية"}),
    ("government", {"en": "Government Entity", "ar": "جهة حكومية"}),
    ("events", {"en": "Events & Exhibitions", "ar": "فعاليات ومعارض"}),
]

CITIES = [
    ("riyadh", {"en": "Riyadh", "ar": "الرياض"}, "24.7136", "46.6753"),
    ("jeddah", {"en": "Jeddah", "ar": "جدة"}, "21.4858", "39.1925"),
    ("makkah", {"en": "Makkah", "ar": "مكة المكرمة"}, "21.3891", "39.8579"),
    ("madinah", {"en": "Madinah", "ar": "المدينة المنورة"}, "24.5247", "39.5692"),
    ("dammam", {"en": "Dammam", "ar": "الدمام"}, "26.4207", "50.0888"),
    ("khobar", {"en": "Al Khobar", "ar": "الخبر"}, "26.2172", "50.1971"),
    ("dhahran", {"en": "Dhahran", "ar": "الظهران"}, "26.2361", "50.0393"),
    ("taif", {"en": "Taif", "ar": "الطائف"}, "21.2854", "40.4245"),
    ("tabuk", {"en": "Tabuk", "ar": "تبوك"}, "28.3835", "36.5662"),
    ("abha", {"en": "Abha", "ar": "أبها"}, "18.2164", "42.5053"),
    ("buraidah", {"en": "Buraidah", "ar": "بريدة"}, "26.3592", "43.9818"),
    ("hail", {"en": "Hail", "ar": "حائل"}, "27.5114", "41.7208"),
    ("jazan", {"en": "Jazan", "ar": "جازان"}, "16.8894", "42.5706"),
    ("najran", {"en": "Najran", "ar": "نجران"}, "17.5656", "44.2289"),
    ("al_ahsa", {"en": "Al Ahsa", "ar": "الأحساء"}, "25.3647", "49.5856"),
]


def seed_reference_data(db: Session) -> None:
    roles = {r.code: r for r in db.scalars(select(Role))}
    for code, portal, name in ROLES:
        if code in roles:
            roles[code].name, roles[code].portal = name, portal
        else:
            db.add(Role(code=code, portal=portal, name=name))

    statuses = {s.code: s for s in db.scalars(select(RequestStatus))}
    for code, order, terminal, name in REQUEST_STATUSES:
        if code in statuses:
            statuses[code].name, statuses[code].sort_order, statuses[code].is_terminal = name, order, terminal
        else:
            db.add(RequestStatus(code=code, sort_order=order, is_terminal=terminal, name=name))

    sectors = {s.code: s for s in db.scalars(select(Sector))}
    for code, name in SECTORS:
        if code in sectors:
            sectors[code].name = name
        else:
            db.add(Sector(code=code, name=name))

    cities = {c.code: c for c in db.scalars(select(City))}
    for code, name, lat, lng in CITIES:
        if code in cities:
            cities[code].name = name
        else:
            db.add(City(code=code, name=name, latitude=Decimal(lat), longitude=Decimal(lng)))

    db.commit()


def seed_super_admin(db: Session) -> None:
    if not (settings.SEED_ADMIN_EMAIL and settings.SEED_ADMIN_PASSWORD):
        logger.info("SEED_ADMIN_EMAIL / SEED_ADMIN_PASSWORD not set; skipping super admin.")
        return
    email = settings.SEED_ADMIN_EMAIL.lower()
    if db.scalar(select(User.id).where(User.email == email)):
        return
    role = db.scalar(select(Role).where(Role.code == RoleCode.SUPER_ADMIN))
    db.add(User(email=email, full_name=settings.SEED_ADMIN_NAME, hashed_password=hash_password(settings.SEED_ADMIN_PASSWORD), role=role))
    db.commit()


# ---------------------------------------------------------------------------
# Demo scenario
# ---------------------------------------------------------------------------
DEMO_ADMIN_EMAIL = "admin@irongate.sa"
DEMO_FIRM_EMAIL = "firm@irongate.sa"
DEMO_FACILITY_EMAIL = "facility@irongate.sa"
DEMO_GUARD_EMAIL = "guard@irongate.sa"

DEMO_FIRM = {"name": "Najd Guard Co.", "name_ar": "شركة نجد للحراسات الأمنية", "license": "MOI-DEMO-1001", "cr": "1010000001", "rating": "4.80"}
RIVAL_FIRM = {"name": "Shield Security Services", "name_ar": "شركة الدرع للخدمات الأمنية", "license": "MOI-DEMO-2002", "cr": "1010000002", "rating": "4.50"}
PENDING_FIRM = {"name": "Al-Amn Guarding Co.", "name_ar": "شركة الأمن للحراسات", "license": "MOI-DEMO-3003", "cr": "1010000003", "rating": None}
BYOC_SITE = {"name": "Al Nakheel Business Park", "name_ar": "مجمع النخيل للأعمال", "address": "King Fahd Rd, Al Nakheel, Riyadh",
             "lat": Decimal("24.7743000"), "lng": Decimal("46.6386000"), "radius": 250}
SITE = {"name": "Riyadh Park Mall", "name_ar": "رياض بارك مول", "address": "Northern Ring Rd, Al Aqiq, Riyadh",
        "lat": Decimal("24.7560000"), "lng": Decimal("46.6290000"), "radius": 300}

GUARD_NAMES = [
    ("Faisal Al-Qahtani", "فيصل القحطاني"), ("Omar Al-Harbi", "عمر الحربي"), ("Saad Al-Mutairi", "سعد المطيري"),
    ("Yousef Al-Rashid", "يوسف الراشد"), ("Nasser Al-Shehri", "ناصر الشهري"), ("Khalid Al-Zahrani", "خالد الزهراني"),
    ("Turki Al-Dosari", "تركي الدوسري"), ("Majed Al-Otaibi", "ماجد العتيبي"), ("Abdullah Al-Ghamdi", "عبدالله الغامدي"),
    ("Fahad Al-Subaie", "فهد السبيعي"), ("Sultan Al-Anazi", "سلطان العنزي"), ("Bandar Al-Shammari", "بندر الشمري"),
    ("Hamad Al-Juhani", "حمد الجهني"), ("Ali Al-Malki", "علي المالكي"),
]
RIVAL_GUARD_NAMES = [
    ("Ibrahim Al-Saeed", "إبراهيم السعيد"), ("Mohammed Al-Yami", "محمد اليامي"), ("Rakan Al-Balawi", "راكان البلوي"),
    ("Mishal Al-Enezi", "مشعل العنزي"), ("Waleed Al-Sahli", "وليد السهلي"),
]

# (key, title, guards, start offset days, duration days, daily hours, status)
DEMO_REQUESTS = [
    ("active", "Main entrances — round-the-clock coverage", 4, -10, 90, 12, RequestStatusCode.ACTIVE),
    ("awarded", "Parking levels P1–P3 patrol", 3, 5, 90, 8, RequestStatusCode.AWARDED),
    ("open_bid", "Weekend events — Exhibition Hall B", 4, 10, 30, 8, RequestStatusCode.OPEN),
    ("open_new", "Ramadan night shift — food court", 3, 14, 30, 12, RequestStatusCode.OPEN),
]


def _offset(lat: Decimal, lng: Decimal, north_m: float, east_m: float) -> Tuple[Decimal, Decimal]:
    dlat = north_m / 111_320
    dlng = east_m / (111_320 * cos(radians(float(lat))))
    return (lat + Decimal(str(round(dlat, 7)))).quantize(Decimal("0.0000001")), (lng + Decimal(str(round(dlng, 7)))).quantize(Decimal("0.0000001"))


def _ensure_user(db: Session, email: str, full_name: str, role: Role, password_hash: str, **org) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, full_name=full_name, hashed_password=password_hash, role=role, **org)
        db.add(user)
        db.flush()
    return user


def _ensure_firm(db: Session, spec: dict, riyadh: City, jeddah: City, admin: Optional[User], now: datetime,
                 approved: bool = True) -> Firm:
    firm = db.scalar(select(Firm).where(Firm.moi_license_number == spec["license"]))
    if firm is None:
        firm = Firm(
            name=spec["name"], name_ar=spec["name_ar"], moi_license_number=spec["license"], commercial_registration=spec["cr"],
            license_expiry_date=date(now.year + 3, 12, 31), headquarters_city=riyadh, operating_cities=[riyadh, jeddah],
            rating=Decimal(spec["rating"]) if spec["rating"] else None,
            status=FirmStatus.APPROVED if approved else FirmStatus.PENDING,
            reviewed_by=admin if approved else None, reviewed_at=now if approved else None,
        )
        db.add(firm)
        db.flush()
    return firm


def _ensure_guards(db: Session, firm: Firm, names: List[Tuple[str, str]], id_prefix: str, city: City,
                   pending: int, now: datetime, rng: random.Random) -> List[Guard]:
    guards = []
    for i, (name, name_ar) in enumerate(names):
        national_id = f"{id_prefix}{i + 1:03d}"
        guard = db.scalar(select(Guard).where(Guard.national_id == national_id))
        if guard is None:
            verified = i < len(names) - pending
            checked = now - timedelta(days=rng.randint(1, 40), hours=rng.randint(0, 23))
            guard = Guard(
                firm=firm, national_id=national_id, full_name=name, full_name_ar=name_ar, city=city,
                phone=f"05{rng.randint(10_000_000, 99_999_999)}",
                shamoos_status=ShamoosStatus.VERIFIED if verified else ShamoosStatus.PENDING,
                shamoos_checked_at=checked if verified else None,
                shamoos_reference=f"SHM-{rng.getrandbits(40):010X}" if verified else None,
            )
            db.add(guard)
            db.flush()
            if verified:
                db.add(ShamoosVerificationLog(
                    guard=guard, national_id=national_id, result=ShamoosCheckResult.VERIFIED,
                    reference=guard.shamoos_reference, latency_ms=rng.randint(180, 640), created_at=checked,
                ))
        guards.append(guard)
    firm.total_guards = len(guards)
    return guards


def _refresh_demo_logs(db: Session, now: datetime) -> None:
    """Keep demo Shamoos traffic inside the 24 h health window so the ops dashboard shows live stats."""
    logs = db.scalars(
        select(ShamoosVerificationLog)
        .where(ShamoosVerificationLog.national_id.like("1000000%") | ShamoosVerificationLog.national_id.like("2000000%"))
        .order_by(ShamoosVerificationLog.id)
    ).all()
    for i, log in enumerate(reversed(logs)):
        log.created_at = now - timedelta(minutes=25 + i * 61)


def _clear_open_shifts(db: Session, contract: Contract, now: datetime) -> None:
    """Remove a demo contract's open shifts (penalised ones are closed out instead — a penalty references them)."""
    for shift in list(contract.shifts):
        if shift.status not in (ShiftStatus.SCHEDULED, ShiftStatus.IN_PROGRESS):
            continue
        if shift.penalty is None:
            db.delete(shift)
        else:  # referenced by an SLA penalty: close it out instead of deleting
            shift.status = ShiftStatus.COMPLETED
            shift.clock_out_at = shift.clock_out_at or now
            shift.breach_total_minutes = shift.breach_minutes(now)
            shift.breach_active_since = None
    db.flush()
    db.expire(contract, ["shifts"])


def _refresh_demo_shifts(db: Session, contract: Contract, guards: List[Guard], hr_or_manager: Optional[User], now: datetime) -> None:
    """Rebuild the demo contract's open shifts around *now*."""
    _clear_open_shifts(db, contract, now)
    lat, lng = SITE["lat"], SITE["lng"]
    base = dict(contract=contract, assigned_by=hr_or_manager)

    # Demo guard (guard@irongate.sa): shift already open for clock-in, plus the next three days.
    for day in range(4):
        start = now - timedelta(minutes=20) + timedelta(days=day)
        db.add(Shift(guard=guards[0], scheduled_start=start, scheduled_end=start + timedelta(hours=12), **base))

    # Colleagues on post inside the fence.
    for guard, (north, east) in zip(guards[1:4], [(80, -60), (-110, 40), (30, 150)]):
        glat, glng = _offset(lat, lng, north, east)
        start = now - timedelta(hours=2)
        db.add(Shift(
            guard=guard, scheduled_start=start, scheduled_end=start + timedelta(hours=12), status=ShiftStatus.IN_PROGRESS,
            clock_in_at=start + timedelta(minutes=3), clock_in_latitude=glat, clock_in_longitude=glng,
            last_latitude=glat, last_longitude=glng, last_location_at=now - timedelta(minutes=2), **base,
        ))

    # One guard currently outside the geofence (~450 m NE) — feeds the SLA penalty job after 30 min.
    blat, blng = _offset(lat, lng, 320, 330)
    start = now - timedelta(hours=3)
    db.add(Shift(
        guard=guards[4], scheduled_start=start, scheduled_end=start + timedelta(hours=12), status=ShiftStatus.IN_PROGRESS,
        clock_in_at=start + timedelta(minutes=5), clock_in_latitude=lat, clock_in_longitude=lng,
        last_latitude=blat, last_longitude=blng, last_location_at=now - timedelta(minutes=1),
        geofence_breach_flag=True, breach_active_since=now - timedelta(minutes=12), **base,
    ))

    # Next shift of the day (not yet on site).
    start = now + timedelta(hours=3)
    db.add(Shift(guard=guards[5], scheduled_start=start, scheduled_end=start + timedelta(hours=12), **base))


def _refresh_byoc_shifts(db: Session, contract: Contract, guards: List[Guard], now: datetime) -> None:
    """Guards of the imported (BYOC) contract: four on post, one arriving later."""
    _clear_open_shifts(db, contract, now)
    for guard, (north, east) in zip(guards[:4], [(60, 40), (-90, -30), (20, -120), (-40, 110)]):
        glat, glng = _offset(BYOC_SITE["lat"], BYOC_SITE["lng"], north, east)
        start = now - timedelta(hours=4)
        db.add(Shift(
            contract=contract, guard=guard, scheduled_start=start, scheduled_end=start + timedelta(hours=12),
            status=ShiftStatus.IN_PROGRESS, clock_in_at=start + timedelta(minutes=4), clock_in_latitude=glat, clock_in_longitude=glng,
            last_latitude=glat, last_longitude=glng, last_location_at=now - timedelta(minutes=3),
        ))
    start = now + timedelta(hours=2)
    db.add(Shift(contract=contract, guard=guards[4], scheduled_start=start, scheduled_end=start + timedelta(hours=12)))


def _seed_byoc(db: Session, rival: Firm, admin: User, sector: Sector, city: City, now: datetime) -> Contract:
    """A second facility that onboarded via 'Import Existing Contract' with its current provider."""
    contract = db.scalar(select(Contract).where(Contract.contract_number == "BYOC-DEMO-0001"))
    if contract is not None:
        return contract
    today = now.date()
    park = Facility(name=BYOC_SITE["name"], name_ar=BYOC_SITE["name_ar"], address=BYOC_SITE["address"], sector=sector, city=city,
                    latitude=BYOC_SITE["lat"], longitude=BYOC_SITE["lng"], geofence_radius_m=BYOC_SITE["radius"])
    req = GuardRequest(facility=park, created_by=admin, title="Existing guarding contract — Towers A & B", guard_count=5, daily_hours=12,
                       start_date=today - timedelta(days=60), end_date=today + timedelta(days=304),
                       status_code=RequestStatusCode.ACTIVE.value, created_at=now - timedelta(days=21))
    bid = Bid(request=req, firm=rival, submitted_by=admin, price_per_guard=Decimal("54000.00"), total_price=Decimal("270000.00"),
              status=BidStatus.ACCEPTED, decided_at=now - timedelta(days=21))
    contract = Contract(
        bid=bid, contract_number="BYOC-DEMO-0001", start_date=req.start_date, end_date=req.end_date, total_value=Decimal("270000.00"),
        status=ContractStatus.ACTIVE, sla_breach_threshold_minutes=30, sla_penalty_per_breach=Decimal("500.00"),
        sla_max_penalty_percent=Decimal("10.00"), sla_details={"source": "imported", "external_reference": "NBP-SEC-2025-014"},
        facility_approved_by=admin, facility_approved_at=now - timedelta(days=21), firm_signed_at=now - timedelta(days=20),
        created_at=now - timedelta(days=21),
    )
    db.add_all([park, req, bid, contract])
    db.flush()
    return contract


# Completed marketplace jobs in previous months: (months ago, title, guards, total SAR, winning firm key)
HISTORY = [
    (5, "Riyadh Season pop-up — Gate C", 3, "42000.00", "rival"),
    (4, "Eid al-Adha crowd control", 6, "58500.00", "firm"),
    (3, "Summer festival — outdoor plaza", 5, "76000.00", "rival"),
    (2, "Back-to-school traffic marshals", 4, "91500.00", "firm"),
    (1, "Summer nights programme — food court", 7, "118000.00", "firm"),
]


def _history_created(now: datetime, months_ago: int) -> datetime:
    local = riyadh(now)  # billing months are Riyadh months
    y, m = local.year, local.month - months_ago
    while m <= 0:
        y, m = y - 1, m + 12
    return datetime(y, m, 10, 9, 0)


def _retime_demo_contracts(db: Session, now: datetime) -> None:
    """Keep demo GMV history anchored to the current month on every seed run."""
    for n, (months_ago, *_rest) in enumerate(HISTORY, start=1):
        contract = db.scalar(select(Contract).where(Contract.contract_number == f"IG-HIST-{n:02d}"))
        if contract is None:
            continue
        created = _history_created(now, months_ago)
        req = contract.bid.request
        req.created_at = created - timedelta(days=4)
        req.start_date = (created + timedelta(days=7)).date()
        req.end_date = req.start_date + timedelta(days=20)
        contract.start_date, contract.end_date = req.start_date, req.end_date
        contract.bid.decided_at = contract.created_at = created
        contract.firm_signed_at = created + timedelta(days=1)
        contract.facility_approved_at = created + timedelta(days=2)
    # The freshly awarded demo contract (still awaiting signature) is "this month's" marketplace deal.
    awarded = db.scalar(select(Contract).where(Contract.contract_number == "IG-DEMO-0002"))
    if awarded is not None and awarded.firm_signed_at is None:
        awarded.created_at = max(now - timedelta(hours=1), month_start(now))


def _seed_history(db: Session, facility: Facility, facility_user: User, firms: Dict[str, Firm], submitter: User, now: datetime) -> None:
    """Past, completed marketplace contracts so GMV trends have history (created once)."""
    for n, (months_ago, title, guards, total, key) in enumerate(HISTORY, start=1):
        if db.scalar(select(Contract.id).where(Contract.contract_number == f"IG-HIST-{n:02d}")) is not None:
            continue
        created = _history_created(now, months_ago)
        start = (created + timedelta(days=7)).date()
        req = GuardRequest(facility=facility, created_by=facility_user, title=title, guard_count=guards, daily_hours=12,
                           start_date=start, end_date=start + timedelta(days=20), status_code=RequestStatusCode.COMPLETED.value,
                           created_at=created - timedelta(days=4))
        value = Decimal(total)
        bid = Bid(request=req, firm=firms[key], submitted_by=submitter, price_per_guard=(value / guards).quantize(Decimal("0.01")),
                  total_price=value, status=BidStatus.ACCEPTED, decided_at=created)
        db.add_all([req, bid, Contract(
            bid=bid, contract_number=f"IG-HIST-{n:02d}", start_date=req.start_date, end_date=req.end_date, total_value=value,
            status=ContractStatus.COMPLETED, sla_breach_threshold_minutes=30, sla_penalty_per_breach=Decimal("500.00"),
            sla_max_penalty_percent=Decimal("10.00"), firm_signed_at=created + timedelta(days=1),
            facility_approved_by=facility_user, facility_approved_at=created + timedelta(days=2), created_at=created,
        )])
    db.flush()


def seed_demo_data(db: Session, now: Optional[datetime] = None) -> None:
    if not settings.SEED_DEMO_DATA:
        return
    now = now or utcnow()
    today = now.date()
    rng = random.Random(1001)
    password = hash_password(settings.SEED_DEMO_PASSWORD)

    roles: Dict[RoleCode, Role] = {r.code: r for r in db.scalars(select(Role))}
    cities = {c.code: c for c in db.scalars(select(City))}
    mall = db.scalar(select(Sector).where(Sector.code == "shopping_mall"))
    riyadh, jeddah = cities["riyadh"], cities["jeddah"]

    admin = _ensure_user(db, DEMO_ADMIN_EMAIL, "Platform Admin", roles[RoleCode.SUPER_ADMIN], password)
    firm = _ensure_firm(db, DEMO_FIRM, riyadh, jeddah, admin, now)
    rival = _ensure_firm(db, RIVAL_FIRM, riyadh, jeddah, admin, now)
    _ensure_firm(db, PENDING_FIRM, riyadh, jeddah, admin, now, approved=False)
    firm_user = _ensure_user(db, DEMO_FIRM_EMAIL, "Abdulrahman Al-Saud", roles[RoleCode.FIRM_MANAGER], password, firm=firm)

    facility_user = db.scalar(select(User).where(User.email == DEMO_FACILITY_EMAIL))
    if facility_user is None:
        facility = Facility(
            name=SITE["name"], name_ar=SITE["name_ar"], sector=mall, city=riyadh, address=SITE["address"],
            latitude=SITE["lat"], longitude=SITE["lng"], geofence_radius_m=SITE["radius"],
        )
        db.add(facility)
        facility_user = _ensure_user(db, DEMO_FACILITY_EMAIL, "Reem Al-Otaibi", roles[RoleCode.FACILITY_MANAGER], password, facility=facility)
    facility = facility_user.facility

    guards = _ensure_guards(db, firm, GUARD_NAMES, "1000000", riyadh, pending=2, now=now, rng=rng)
    rival_guards = _ensure_guards(db, rival, RIVAL_GUARD_NAMES, "2000000", riyadh, pending=0, now=now, rng=rng)
    if db.scalar(select(ShamoosVerificationLog.id).where(ShamoosVerificationLog.result == ShamoosCheckResult.ERROR)) is None:
        db.add(ShamoosVerificationLog(national_id="1000000099", result=ShamoosCheckResult.ERROR, latency_ms=5000,
                                      error_message="Upstream timeout (demo)", created_at=now - timedelta(hours=5)))

    guard_user = db.scalar(select(User).where(User.email == DEMO_GUARD_EMAIL))
    if guard_user is None:
        guard_user = _ensure_user(db, DEMO_GUARD_EMAIL, GUARD_NAMES[0][0], roles[RoleCode.SECURITY_GUARD], password, firm=firm)
    if guards[0].user_id is None:
        guards[0].user = guard_user

    # Requests / bids / contracts — created once.
    if not db.scalar(select(GuardRequest.id).where(GuardRequest.facility_id == facility.id)):
        created: Dict[str, GuardRequest] = {}
        for key, title, count, start_off, days, hours, status in DEMO_REQUESTS:
            req = GuardRequest(
                facility=facility, created_by=facility_user, title=title, guard_count=count, daily_hours=hours,
                start_date=today + timedelta(days=start_off), end_date=today + timedelta(days=start_off + days - 1),
                status_code=status.value, created_at=now - timedelta(days=max(1, 14 - start_off)),
            )
            db.add(req)
            created[key] = req
        db.flush()

        def bid(req: GuardRequest, who: Firm, price: str, status: BidStatus) -> Bid:
            b = Bid(request=req, firm=who, submitted_by=firm_user, price_per_guard=Decimal(price),
                    total_price=Decimal(price) * req.guard_count, status=status,
                    decided_at=now if status in (BidStatus.ACCEPTED, BidStatus.REJECTED) else None)
            db.add(b)
            return b

        won = bid(created["active"], firm, "27000.00", BidStatus.ACCEPTED)
        bid(created["active"], rival, "28400.00", BidStatus.REJECTED)
        awarded = bid(created["awarded"], firm, "21000.00", BidStatus.ACCEPTED)
        bid(created["awarded"], rival, "22500.00", BidStatus.REJECTED)
        bid(created["open_bid"], firm, "9400.00", BidStatus.SUBMITTED)
        bid(created["open_bid"], rival, "8750.00", BidStatus.SUBMITTED)
        db.flush()

        sla = dict(sla_breach_threshold_minutes=30, sla_penalty_per_breach=Decimal("500.00"), sla_max_penalty_percent=Decimal("10.00"),
                   sla_details={"response_time_minutes": 15, "replacement_hours": 4})
        db.add(Contract(
            bid=won, contract_number="IG-DEMO-0001", start_date=created["active"].start_date, end_date=created["active"].end_date,
            total_value=won.total_price, status=ContractStatus.ACTIVE, firm_signed_by=firm_user, firm_signed_at=now - timedelta(days=12),
            facility_approved_by=facility_user, facility_approved_at=now - timedelta(days=11), **sla,
        ))
        db.add(Contract(
            bid=awarded, contract_number="IG-DEMO-0002", start_date=created["awarded"].start_date, end_date=created["awarded"].end_date,
            total_value=awarded.total_price, status=ContractStatus.PENDING_FIRM_SIGNATURE, **sla,
        ))
        db.flush()

    _refresh_demo_logs(db, now)
    active_contract = db.scalar(select(Contract).where(Contract.contract_number == "IG-DEMO-0001"))
    if active_contract is not None:
        _refresh_demo_shifts(db, active_contract, guards, firm_user, now)

    _seed_history(db, facility, facility_user, {"firm": firm, "rival": rival}, firm_user, now)
    offices = db.scalar(select(Sector).where(Sector.code == "corporate_office"))
    byoc = _seed_byoc(db, rival, admin, offices, riyadh, now)
    _refresh_byoc_shifts(db, byoc, rival_guards, now)

    _retime_demo_contracts(db, now)
    # Contracts are created before they are signed (keeps the monthly GMV chart truthful for demo data).
    for c in db.scalars(select(Contract).where(Contract.firm_signed_at.is_not(None))):
        if c.created_at > c.firm_signed_at:
            c.created_at = c.firm_signed_at - timedelta(days=1)

    db.commit()


def main() -> None:
    from app.db.session import SessionLocal

    logging.basicConfig(level=logging.INFO)
    with SessionLocal() as db:
        seed_reference_data(db)
        seed_super_admin(db)
        seed_demo_data(db)
    logger.info("Seed complete.")
    if settings.SEED_DEMO_DATA:
        for email, role in [(DEMO_ADMIN_EMAIL, "super_admin"), (DEMO_FIRM_EMAIL, "firm_manager"),
                            (DEMO_FACILITY_EMAIL, "facility_manager"), (DEMO_GUARD_EMAIL, "security_guard")]:
            logger.info("  demo account: %-22s %s", email, role)


if __name__ == "__main__":
    main()
