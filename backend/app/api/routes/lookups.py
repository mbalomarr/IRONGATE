"""Public, localized lookup lists (names come from the JSON `name` columns)."""
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models import City, Firm, RequestStatus, Role, Sector
from app.models.enums import FirmStatus
from app.schemas.common import APIResponse, ok
from app.schemas.lookup import LookupOut

router = APIRouter(prefix="/lookups", tags=["Lookups"])


@router.get("/cities", response_model=APIResponse[List[LookupOut]])
def list_cities(db: Session = Depends(get_db)):
    rows = db.scalars(select(City).where(City.is_active.is_(True)).order_by(City.id)).all()
    return ok([LookupOut(id=c.id, code=c.code, name=c.localized_name()) for c in rows])


@router.get("/sectors", response_model=APIResponse[List[LookupOut]])
def list_sectors(db: Session = Depends(get_db)):
    rows = db.scalars(select(Sector).where(Sector.is_active.is_(True)).order_by(Sector.id)).all()
    return ok([LookupOut(id=s.id, code=s.code, name=s.localized_name()) for s in rows])


@router.get("/request-statuses", response_model=APIResponse[List[LookupOut]])
def list_request_statuses(db: Session = Depends(get_db)):
    rows = db.scalars(select(RequestStatus).order_by(RequestStatus.sort_order)).all()
    return ok([LookupOut(code=s.code, name=s.localized_name()) for s in rows])


@router.get("/firms", response_model=APIResponse[List[LookupOut]])
def list_approved_firms(db: Session = Depends(get_db)):
    """Directory of approved security firms (e.g. to pick the provider of an imported contract)."""
    rows = db.scalars(select(Firm).where(Firm.status == FirmStatus.APPROVED).order_by(Firm.name)).all()
    return ok([LookupOut(id=f.id, code=f.moi_license_number, name=f.display_name()) for f in rows])


@router.get("/roles", response_model=APIResponse[List[LookupOut]])
def list_roles(db: Session = Depends(get_db)):
    rows = db.scalars(select(Role).order_by(Role.id)).all()
    return ok([LookupOut(id=r.id, code=r.code.value, name=r.localized_name()) for r in rows])
