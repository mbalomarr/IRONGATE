"""Marketplace flow: guard request -> firm bids -> facility accepts -> firm signs -> facility approves."""
import secrets
from decimal import Decimal
from typing import Dict, List, Optional

from fastapi import APIRouter, Body, Depends, Query, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user, get_db, require_permissions
from app.core.exceptions import AppException
from app.core.permissions import CLIENT_ROLES, FIRM_ROLES, PLATFORM_ROLES, Permission, has_permissions
from app.models import Bid, Contract, Facility, Firm, GuardRequest, User
from app.models.base import utcnow
from app.models.enums import BidStatus, ContractStatus, FirmStatus, RequestStatusCode, RoleCode
from app.schemas.bidding import (
    BidCreate,
    BidOut,
    ContractImportIn,
    ContractOut,
    ContractTermsIn,
    FirmRecommendationOut,
    RequestCreate,
    RequestOut,
)
from app.schemas.common import ERROR_RESPONSES, APIResponse, NamedRef, Page, ok
from app.core.config import settings
from app.services.matching import available_guard_count, recommend_firms
from app.services.saas import IMPORTED, is_imported

router = APIRouter(tags=["Bidding"], responses=ERROR_RESPONSES)

CENT = Decimal("0.01")
_REQUEST_LOAD = (
    joinedload(GuardRequest.facility).joinedload(Facility.city),
    joinedload(GuardRequest.facility).joinedload(Facility.sector),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _firm_service_city_ids(firm: Firm) -> List[int]:
    return list({firm.headquarters_city_id, *(c.id for c in firm.operating_cities)})


def _get_request(db: Session, request_id: int, for_update: bool = False) -> GuardRequest:
    req = db.get(GuardRequest, request_id, options=_REQUEST_LOAD, with_for_update=for_update or None)
    if req is None:
        raise AppException("request.not_found", status.HTTP_404_NOT_FOUND)
    return req


def _assert_can_view_request(db: Session, user: User, req: GuardRequest) -> None:
    role = user.role.code
    if role in PLATFORM_ROLES:
        return
    if role in CLIENT_ROLES and req.facility_id == user.facility_id:
        return
    if role in FIRM_ROLES and user.firm is not None:
        in_area = req.facility.city_id in _firm_service_city_ids(user.firm)
        has_bid = db.scalar(select(Bid.id).where(Bid.request_id == req.id, Bid.firm_id == user.firm_id)) is not None
        if (in_area and req.status_code == RequestStatusCode.OPEN.value) or has_bid:
            return
    raise AppException("request.not_found", status.HTTP_404_NOT_FOUND)  # don't leak existence


def _bid_counts(db: Session, request_ids: List[int]) -> Dict[int, int]:
    if not request_ids:
        return {}
    rows = db.execute(
        select(Bid.request_id, func.count(Bid.id))
        .where(Bid.request_id.in_(request_ids), Bid.status != BidStatus.WITHDRAWN)
        .group_by(Bid.request_id)
    )
    return {rid: count for rid, count in rows}


def _get_bid(db: Session, bid_id: int, for_update: bool = False) -> Bid:
    bid = db.get(Bid, bid_id, with_for_update=for_update or None)
    if bid is None:
        raise AppException("bid.not_found", status.HTTP_404_NOT_FOUND)
    return bid


def _get_contract(db: Session, contract_id: int) -> Contract:
    contract = db.get(Contract, contract_id)
    if contract is None:
        raise AppException("contract.not_found", status.HTTP_404_NOT_FOUND)
    return contract


def _require_approved_firm(user: User) -> Firm:
    if user.firm is None:
        raise AppException("firm.not_linked", status.HTTP_403_FORBIDDEN)
    if user.firm.status != FirmStatus.APPROVED:
        raise AppException("firm.not_approved", status.HTTP_403_FORBIDDEN)
    return user.firm


def _new_contract_number() -> str:
    return f"IG-{utcnow():%Y%m%d}-{secrets.token_hex(3).upper()}"


# ---------------------------------------------------------------------------
# Guard requests
# ---------------------------------------------------------------------------
@router.post("/requests", status_code=status.HTTP_201_CREATED, response_model=APIResponse[RequestOut])
def create_request(
    payload: RequestCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions(Permission.REQUEST_CREATE)),
):
    if user.facility_id is None:
        raise AppException("facility.not_linked", status.HTTP_403_FORBIDDEN)
    req = GuardRequest(
        facility_id=user.facility_id,
        created_by_id=user.id,
        status_code=RequestStatusCode.OPEN.value,
        **payload.model_dump(),
    )
    db.add(req)
    db.commit()
    return ok(RequestOut.from_model(_get_request(db, req.id)), "request.created")


@router.get("/requests", response_model=APIResponse[Page[RequestOut]])
def list_requests(
    status_code: Optional[RequestStatusCode] = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions(Permission.REQUEST_VIEW)),
):
    """Scoped by role: clients see their facility's requests, firms see open requests in their
    service area plus anything they bid on, platform staff see everything."""
    stmt = select(GuardRequest).join(Facility, Facility.id == GuardRequest.facility_id)
    role = user.role.code
    if role in CLIENT_ROLES:
        stmt = stmt.where(GuardRequest.facility_id == user.facility_id)
    elif role in FIRM_ROLES:
        if user.firm is None:
            raise AppException("firm.not_linked", status.HTTP_403_FORBIDDEN)
        own_bids = select(Bid.request_id).where(Bid.firm_id == user.firm_id)
        stmt = stmt.where(
            or_(
                and_(
                    GuardRequest.status_code == RequestStatusCode.OPEN.value,
                    Facility.city_id.in_(_firm_service_city_ids(user.firm)),
                ),
                GuardRequest.id.in_(own_bids),
            )
        )
    if status_code is not None:
        stmt = stmt.where(GuardRequest.status_code == status_code.value)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.options(*_REQUEST_LOAD).order_by(GuardRequest.created_at.desc()).limit(limit).offset(offset)
    ).unique().all()
    counts = _bid_counts(db, [r.id for r in rows])
    items = [RequestOut.from_model(r, counts.get(r.id, 0)) for r in rows]
    return ok(Page(items=items, total=total, limit=limit, offset=offset))


@router.get("/requests/{request_id}", response_model=APIResponse[RequestOut])
def get_request(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions(Permission.REQUEST_VIEW)),
):
    req = _get_request(db, request_id)
    _assert_can_view_request(db, user, req)
    return ok(RequestOut.from_model(req, _bid_counts(db, [req.id]).get(req.id, 0)))


@router.get("/requests/{request_id}/recommended-firms", response_model=APIResponse[List[FirmRecommendationOut]])
def recommended_firms(
    request_id: int,
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions(Permission.BID_COMPARE, Permission.REQUEST_MONITOR, any_of=True)),
):
    """Smart matching: approved firms serving the facility's city with enough available verified guards."""
    req = _get_request(db, request_id)
    _assert_can_view_request(db, user, req)
    matches = recommend_firms(db, req, limit)
    return ok(
        [
            FirmRecommendationOut(
                firm=NamedRef(id=m.firm.id, name=m.firm.display_name()),
                rating=m.firm.rating,
                verified_guards=m.verified_guards,
                available_guards=m.available_guards,
                headquartered_in_city=m.headquartered_in_city,
                score=m.score,
            )
            for m in matches
        ]
    )


# ---------------------------------------------------------------------------
# Bids
# ---------------------------------------------------------------------------
@router.post("/requests/{request_id}/bids", status_code=status.HTTP_201_CREATED, response_model=APIResponse[BidOut])
def submit_bid(
    request_id: int,
    payload: BidCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions(Permission.BID_SUBMIT)),
):
    firm = _require_approved_firm(user)
    req = _get_request(db, request_id)
    _assert_can_view_request(db, user, req)

    if req.status_code != RequestStatusCode.OPEN.value:
        raise AppException("request.not_open", status.HTTP_409_CONFLICT)
    if req.bidding_deadline is not None and utcnow() > req.bidding_deadline:
        raise AppException("request.bidding_closed", status.HTTP_409_CONFLICT)
    if firm.license_expiry_date < req.end_date:
        raise AppException("firm.license_expires_before_contract", status.HTTP_422_UNPROCESSABLE_ENTITY)

    available = available_guard_count(db, firm.id, req.facility.city_id, req.start_date, req.end_date)
    if available < req.guard_count:
        raise AppException(
            "bid.insufficient_capacity",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            params={"available": available, "required": req.guard_count},
        )

    total_price = (payload.price_per_guard * req.guard_count).quantize(CENT)
    bid = db.scalar(select(Bid).where(Bid.request_id == req.id, Bid.firm_id == firm.id))
    if bid is not None and bid.status != BidStatus.WITHDRAWN:
        raise AppException("bid.already_exists", status.HTTP_409_CONFLICT)
    if bid is None:
        bid = Bid(request_id=req.id, firm_id=firm.id)
        db.add(bid)
    # A previously withdrawn bid is re-opened in place (unique request_id + firm_id).
    bid.submitted_by_id = user.id
    bid.price_per_guard = payload.price_per_guard
    bid.total_price = total_price
    bid.notes = payload.notes
    bid.status = BidStatus.SUBMITTED
    bid.decided_at = None
    db.commit()
    return ok(BidOut.from_model(bid), "bid.submitted")


@router.get("/requests/{request_id}/bids", response_model=APIResponse[List[BidOut]])
def list_request_bids(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Facility Manager: compare all bids (cheapest first). Firm Manager: sees only their own bid."""
    req = _get_request(db, request_id)
    stmt = (
        select(Bid)
        .options(joinedload(Bid.firm))
        .where(Bid.request_id == req.id)
        .order_by(Bid.price_per_guard.asc(), Bid.created_at.asc())
    )
    role = user.role.code
    if role == RoleCode.SUPER_ADMIN:
        pass
    elif has_permissions(role, [Permission.BID_COMPARE]) and req.facility_id == user.facility_id:
        stmt = stmt.where(Bid.status != BidStatus.WITHDRAWN)
    elif has_permissions(role, [Permission.BID_SUBMIT]) and user.firm_id is not None:
        stmt = stmt.where(Bid.firm_id == user.firm_id)
    else:
        raise AppException("common.forbidden", status.HTTP_403_FORBIDDEN)

    bids = db.scalars(stmt).all()
    submitted_prices = [b.price_per_guard for b in bids if b.status == BidStatus.SUBMITTED]
    lowest = min(submitted_prices) if submitted_prices else None
    return ok(
        [
            BidOut.from_model(b, is_lowest=(b.status == BidStatus.SUBMITTED and b.price_per_guard == lowest))
            for b in bids
        ]
    )


@router.get("/bids", response_model=APIResponse[Page[BidOut]])
def list_bids(
    bid_status: Optional[BidStatus] = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions(Permission.BID_COMPARE, Permission.BID_SUBMIT, any_of=True)),
):
    """Facility: bids received on its requests. Firm: its own bids. Super Admin: everything."""
    stmt = select(Bid).join(GuardRequest, GuardRequest.id == Bid.request_id)
    role = user.role.code
    if role == RoleCode.SUPER_ADMIN:
        pass
    elif has_permissions(role, [Permission.BID_COMPARE]) and user.facility_id is not None:
        stmt = stmt.where(GuardRequest.facility_id == user.facility_id, Bid.status != BidStatus.WITHDRAWN)
    elif has_permissions(role, [Permission.BID_SUBMIT]) and user.firm_id is not None:
        stmt = stmt.where(Bid.firm_id == user.firm_id)
    else:
        raise AppException("common.forbidden", status.HTTP_403_FORBIDDEN)
    if bid_status is not None:
        stmt = stmt.where(Bid.status == bid_status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.options(joinedload(Bid.firm), joinedload(Bid.request))
        .order_by(Bid.created_at.desc(), Bid.id.desc())
        .limit(limit)
        .offset(offset)
    ).unique().all()
    return ok(Page(items=[BidOut.from_model(b) for b in rows], total=total, limit=limit, offset=offset))


@router.get("/bids/mine", response_model=APIResponse[List[BidOut]])
def my_bids(
    bid_status: Optional[BidStatus] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions(Permission.BID_SUBMIT)),
):
    if user.firm_id is None:
        raise AppException("firm.not_linked", status.HTTP_403_FORBIDDEN)
    stmt = select(Bid).options(joinedload(Bid.firm)).where(Bid.firm_id == user.firm_id)
    if bid_status is not None:
        stmt = stmt.where(Bid.status == bid_status)
    return ok([BidOut.from_model(b) for b in db.scalars(stmt.order_by(Bid.created_at.desc()))])


@router.post("/bids/{bid_id}/withdraw", response_model=APIResponse[BidOut])
def withdraw_bid(
    bid_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions(Permission.BID_SUBMIT)),
):
    bid = _get_bid(db, bid_id, for_update=True)
    if bid.firm_id != user.firm_id:
        raise AppException("bid.not_found", status.HTTP_404_NOT_FOUND)
    if bid.status != BidStatus.SUBMITTED:
        raise AppException("bid.not_submitted", status.HTTP_409_CONFLICT)
    if bid.request.status_code != RequestStatusCode.OPEN.value:
        raise AppException("request.not_open", status.HTTP_409_CONFLICT)
    bid.status = BidStatus.WITHDRAWN
    bid.decided_at = utcnow()
    db.commit()
    return ok(BidOut.from_model(bid), "bid.withdrawn")


@router.post("/bids/{bid_id}/accept", response_model=APIResponse[ContractOut])
def accept_bid(
    bid_id: int,
    terms: Optional[ContractTermsIn] = Body(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions(Permission.BID_AWARD)),
):
    """Award the request to this bid: other bids are rejected and a contract is drafted for the firm to sign."""
    bid = _get_bid(db, bid_id)
    req = _get_request(db, bid.request_id, for_update=True)  # row lock prevents double-awarding
    if req.facility_id != user.facility_id:
        raise AppException("bid.not_found", status.HTTP_404_NOT_FOUND)
    if req.status_code != RequestStatusCode.OPEN.value:
        raise AppException("request.not_open", status.HTTP_409_CONFLICT)
    if bid.status != BidStatus.SUBMITTED:
        raise AppException("bid.not_submitted", status.HTTP_409_CONFLICT)

    now = utcnow()
    terms = terms or ContractTermsIn()
    for other in req.bids:
        if other.id == bid.id:
            other.status = BidStatus.ACCEPTED
            other.decided_at = now
        elif other.status == BidStatus.SUBMITTED:
            other.status = BidStatus.REJECTED
            other.decided_at = now
    req.status_code = RequestStatusCode.AWARDED.value

    contract = Contract(
        bid=bid,
        contract_number=_new_contract_number(),
        start_date=req.start_date,
        end_date=req.end_date,
        total_value=bid.total_price,
        **terms.model_dump(),
    )
    db.add(contract)
    db.commit()
    return ok(ContractOut.from_model(contract), "bid.accepted")


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------
@router.get("/contracts", response_model=APIResponse[Page[ContractOut]])
def list_contracts(
    contract_status: Optional[ContractStatus] = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions(Permission.CONTRACT_VIEW)),
):
    """Contracts the caller is party to (Super Admin sees all)."""
    stmt = select(Contract).join(Bid, Bid.id == Contract.bid_id).join(GuardRequest, GuardRequest.id == Bid.request_id)
    if user.role.code != RoleCode.SUPER_ADMIN:
        if user.firm_id is not None:
            stmt = stmt.where(Bid.firm_id == user.firm_id)
        elif user.facility_id is not None:
            stmt = stmt.where(GuardRequest.facility_id == user.facility_id)
        else:
            raise AppException("common.forbidden", status.HTTP_403_FORBIDDEN)
    if contract_status is not None:
        stmt = stmt.where(Contract.status == contract_status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Contract.created_at.desc(), Contract.id.desc()).limit(limit).offset(offset)).all()
    return ok(Page(items=[ContractOut.from_model(c) for c in rows], total=total, limit=limit, offset=offset))


@router.get("/contracts/{contract_id}", response_model=APIResponse[ContractOut])
def get_contract(
    contract_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions(Permission.CONTRACT_VIEW)),
):
    contract = _get_contract(db, contract_id)
    bid = contract.bid
    if user.role.code != RoleCode.SUPER_ADMIN and user.firm_id != bid.firm_id and user.facility_id != bid.request.facility_id:
        raise AppException("contract.not_found", status.HTTP_404_NOT_FOUND)
    return ok(ContractOut.from_model(contract))


@router.post("/contracts/{contract_id}/sign", response_model=APIResponse[ContractOut])
def sign_contract(
    contract_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions(Permission.CONTRACT_SIGN)),
):
    contract = _get_contract(db, contract_id)
    if contract.bid.firm_id != user.firm_id:
        raise AppException("contract.not_found", status.HTTP_404_NOT_FOUND)
    if contract.status != ContractStatus.PENDING_FIRM_SIGNATURE:
        raise AppException("contract.invalid_state", status.HTTP_409_CONFLICT)
    contract.firm_signed_by_id = user.id
    contract.firm_signed_at = utcnow()
    if is_imported(contract):
        # BYOC: the facility initiated (and pre-approved) the import; provider confirmation activates tracking.
        contract.status = ContractStatus.ACTIVE
        contract.bid.request.status_code = RequestStatusCode.ACTIVE.value
        db.commit()
        return ok(ContractOut.from_model(contract), "contract.import_confirmed")
    contract.status = ContractStatus.PENDING_FACILITY_APPROVAL
    db.commit()
    return ok(ContractOut.from_model(contract), "contract.signed")


@router.post("/contracts/import", status_code=status.HTTP_201_CREATED, response_model=APIResponse[ContractOut])
def import_contract(
    payload: ContractImportIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions(Permission.BID_AWARD)),
):
    """Bring Your Own Contract: onboard an existing guarding agreement without a tender.

    Stored through the regular request -> bid -> contract chain (tagged ``source: imported``) so tracking,
    shifts and billing work unchanged. The provider confirms once; the contract then goes live.
    """
    if user.facility_id is None:
        raise AppException("facility.not_linked", status.HTTP_403_FORBIDDEN)
    firm = db.get(Firm, payload.firm_id)
    if firm is None or firm.status != FirmStatus.APPROVED:
        raise AppException("contract.provider_unavailable", status.HTTP_422_UNPROCESSABLE_ENTITY)

    now = utcnow()
    value = payload.contract_value.quantize(CENT)
    req = GuardRequest(
        facility_id=user.facility_id,
        created_by_id=user.id,
        title=payload.title or payload.external_reference,
        guard_count=payload.guard_count,
        start_date=payload.start_date,
        end_date=payload.end_date,
        daily_hours=payload.daily_hours,
        status_code=RequestStatusCode.AWARDED.value,
    )
    bid = Bid(
        request=req, firm=firm, submitted_by_id=user.id, status=BidStatus.ACCEPTED, decided_at=now,
        price_per_guard=(value / payload.guard_count).quantize(CENT), total_price=value,
    )
    contract = Contract(
        bid=bid,
        contract_number=f"BYOC-{now:%Y%m%d}-{secrets.token_hex(3).upper()}",
        start_date=payload.start_date,
        end_date=payload.end_date,
        total_value=value,
        sla_breach_threshold_minutes=settings.SLA_BREACH_THRESHOLD_MINUTES,
        sla_penalty_per_breach=settings.SLA_DEFAULT_PENALTY_AMOUNT,
        sla_max_penalty_percent=settings.SLA_DEFAULT_MAX_PENALTY_PERCENT,
        sla_details={"source": IMPORTED, "external_reference": payload.external_reference},
        status=ContractStatus.PENDING_FIRM_SIGNATURE,
        facility_approved_by_id=user.id,
        facility_approved_at=now,
    )
    db.add_all([req, bid, contract])
    db.commit()
    return ok(ContractOut.from_model(contract), "contract.imported", firm=firm.display_name())


@router.post("/contracts/{contract_id}/approve", response_model=APIResponse[ContractOut])
def approve_contract(
    contract_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions(Permission.CONTRACT_APPROVE)),
):
    contract = _get_contract(db, contract_id)
    req = contract.bid.request
    if req.facility_id != user.facility_id:
        raise AppException("contract.not_found", status.HTTP_404_NOT_FOUND)
    if contract.status != ContractStatus.PENDING_FACILITY_APPROVAL:
        raise AppException("contract.invalid_state", status.HTTP_409_CONFLICT)
    contract.status = ContractStatus.ACTIVE
    contract.facility_approved_by_id = user.id
    contract.facility_approved_at = utcnow()
    req.status_code = RequestStatusCode.ACTIVE.value
    db.commit()
    return ok(ContractOut.from_model(contract), "contract.approved")
