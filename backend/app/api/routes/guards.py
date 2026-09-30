from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_db, require_permissions
from app.core.exceptions import AppException
from app.core.permissions import Permission
from app.models import City, Firm, Guard, User
from app.models.enums import EmploymentStatus, RoleCode, ShamoosStatus
from app.schemas.common import ERROR_RESPONSES, APIResponse, Page, ok
from app.schemas.guard import GuardCreate, GuardOut

router = APIRouter(prefix="/guards", tags=["Guard Roster"], responses=ERROR_RESPONSES)


def refresh_roster_size(db: Session, firm: Firm) -> None:
    firm.total_guards = db.scalar(
        select(func.count(Guard.id)).where(Guard.firm_id == firm.id, Guard.employment_status != EmploymentStatus.TERMINATED)
    ) or 0


@router.post("", status_code=status.HTTP_201_CREATED, response_model=APIResponse[GuardOut])
def add_guard(
    payload: GuardCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions(Permission.GUARD_MANAGE)),
):
    """Add a guard to the firm's roster (Shamoos status starts as *pending*)."""
    if user.firm is None:
        raise AppException("firm.not_linked", status.HTTP_403_FORBIDDEN)
    if db.scalar(select(Guard.id).where(Guard.national_id == payload.national_id)):
        raise AppException("guard.national_id_taken", status.HTTP_409_CONFLICT)
    if db.get(City, payload.city_id) is None:
        raise AppException("lookup.city_not_found", status.HTTP_422_UNPROCESSABLE_ENTITY)

    guard = Guard(firm_id=user.firm_id, **payload.model_dump())
    db.add(guard)
    db.flush()
    refresh_roster_size(db, user.firm)
    db.commit()
    return ok(GuardOut.from_model(guard), "guard.created")


@router.get("", response_model=APIResponse[Page[GuardOut]])
def list_guards(
    shamoos_status: Optional[ShamoosStatus] = None,
    firm_id: Optional[int] = Query(None, description="Super Admin only"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions(Permission.GUARD_VIEW)),
):
    stmt = select(Guard).options(selectinload(Guard.city))
    if user.role.code == RoleCode.SUPER_ADMIN:
        if firm_id is not None:
            stmt = stmt.where(Guard.firm_id == firm_id)
    else:
        stmt = stmt.where(Guard.firm_id == user.firm_id)
    if shamoos_status is not None:
        stmt = stmt.where(Guard.shamoos_status == shamoos_status)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Guard.id.desc()).limit(limit).offset(offset)).all()
    return ok(Page(items=[GuardOut.from_model(g) for g in rows], total=total, limit=limit, offset=offset))
