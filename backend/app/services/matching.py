"""Smart matching: recommend firms that can actually staff a request.

Availability in a city = Shamoos-verified, active guards based there
minus guards already committed to overlapping contracts (pending or active) in that city.
"""
from dataclasses import dataclass
from datetime import date
from typing import Dict, Iterable, List, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Bid, City, Contract, Facility, Firm, Guard, GuardRequest
from app.models.enums import ContractStatus, EmploymentStatus, FirmStatus, ShamoosStatus

COMMITTED_CONTRACT_STATUSES = (
    ContractStatus.PENDING_FIRM_SIGNATURE,
    ContractStatus.PENDING_FACILITY_APPROVAL,
    ContractStatus.ACTIVE,
)

# Scoring weights (sum to 1.0)
W_CAPACITY, W_RATING, W_LOCAL = 0.5, 0.3, 0.2
NEUTRAL_RATING = 3.0


@dataclass
class FirmMatch:
    firm: Firm
    verified_guards: int
    available_guards: int
    headquartered_in_city: bool
    score: float


def verified_guard_counts(db: Session, city_id: int, firm_ids: Optional[Iterable[int]] = None) -> Dict[int, int]:
    stmt = (
        select(Guard.firm_id, func.count(Guard.id))
        .where(
            Guard.city_id == city_id,
            Guard.shamoos_status == ShamoosStatus.VERIFIED,
            Guard.employment_status == EmploymentStatus.ACTIVE,
        )
        .group_by(Guard.firm_id)
    )
    if firm_ids is not None:
        stmt = stmt.where(Guard.firm_id.in_(list(firm_ids)))
    return {firm_id: count for firm_id, count in db.execute(stmt)}


def committed_guard_counts(
    db: Session, city_id: int, start: date, end: date, firm_ids: Optional[Iterable[int]] = None
) -> Dict[int, int]:
    stmt = (
        select(Bid.firm_id, func.coalesce(func.sum(GuardRequest.guard_count), 0))
        .join(Contract, Contract.bid_id == Bid.id)
        .join(GuardRequest, GuardRequest.id == Bid.request_id)
        .join(Facility, Facility.id == GuardRequest.facility_id)
        .where(
            Facility.city_id == city_id,
            Contract.status.in_(COMMITTED_CONTRACT_STATUSES),
            Contract.start_date <= end,
            Contract.end_date >= start,
        )
        .group_by(Bid.firm_id)
    )
    if firm_ids is not None:
        stmt = stmt.where(Bid.firm_id.in_(list(firm_ids)))
    return {firm_id: int(total) for firm_id, total in db.execute(stmt)}


def available_guard_count(db: Session, firm_id: int, city_id: int, start: date, end: date) -> int:
    verified = verified_guard_counts(db, city_id, [firm_id]).get(firm_id, 0)
    committed = committed_guard_counts(db, city_id, start, end, [firm_id]).get(firm_id, 0)
    return max(verified - committed, 0)


def recommend_firms(db: Session, request: GuardRequest, limit: int = 10) -> List[FirmMatch]:
    city_id = request.facility.city_id
    firms = db.scalars(
        select(Firm)
        .options(selectinload(Firm.operating_cities))
        .where(
            Firm.status == FirmStatus.APPROVED,
            Firm.license_expiry_date >= request.end_date,
            or_(Firm.headquarters_city_id == city_id, Firm.operating_cities.any(City.id == city_id)),
        )
    ).all()
    if not firms:
        return []

    firm_ids = [f.id for f in firms]
    verified = verified_guard_counts(db, city_id, firm_ids)
    committed = committed_guard_counts(db, city_id, request.start_date, request.end_date, firm_ids)

    matches: List[FirmMatch] = []
    for firm in firms:
        verified_count = verified.get(firm.id, 0)
        available = max(verified_count - committed.get(firm.id, 0), 0)
        if available < request.guard_count:
            continue
        local = firm.headquarters_city_id == city_id
        capacity_score = min(available / request.guard_count, 3.0) / 3.0  # saturates at 3x coverage
        rating_score = float(firm.rating if firm.rating is not None else NEUTRAL_RATING) / 5.0
        score = W_CAPACITY * capacity_score + W_RATING * rating_score + W_LOCAL * (1.0 if local else 0.0)
        matches.append(FirmMatch(firm, verified_count, available, local, round(score, 4)))

    matches.sort(key=lambda m: (m.score, m.available_guards), reverse=True)
    return matches[:limit]
