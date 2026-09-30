"""SaaS billing: per-seat subscription for facilities."""
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permissions
from app.core.config import settings
from app.core.exceptions import AppException
from app.core.permissions import Permission
from app.models import User
from app.models.base import utcnow
from app.schemas.billing import SubscriptionOut
from app.schemas.common import ERROR_RESPONSES, APIResponse, NamedRef, ok
from app.services.saas import facility_subscription

router = APIRouter(prefix="/billing", tags=["Billing"], responses=ERROR_RESPONSES)


@router.get("/subscription", response_model=APIResponse[SubscriptionOut])
def my_subscription(
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions(Permission.INVOICE_VIEW)),
):
    """Current month: platform fee + per-seat fee for every guard tracked on the facility's active contracts."""
    if user.facility_id is None:
        raise AppException("facility.not_linked", status.HTTP_403_FORBIDDEN)
    sub = facility_subscription(db, user.facility_id, utcnow())
    sub["seat_guards"] = [NamedRef(id=g.id, name=g.display_name()) for g in sub["seat_guards"]]
    return ok(SubscriptionOut(currency=settings.CURRENCY, **sub))
