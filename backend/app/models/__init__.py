"""Import every model so `Base.metadata` is complete (Alembic autogenerate relies on this)."""
from app.models.base import Base
from app.models.bid import Bid
from app.models.contract import Contract
from app.models.facility import Facility
from app.models.firm import Firm, firm_cities
from app.models.guard import Guard, ShamoosVerificationLog
from app.models.incident import Incident
from app.models.invoice import Invoice, SLAPenalty
from app.models.lookup import City, RequestStatus, Sector
from app.models.request import GuardRequest
from app.models.shift import Shift
from app.models.user import Role, User

__all__ = [
    "Base",
    "Bid",
    "City",
    "Contract",
    "Facility",
    "Firm",
    "firm_cities",
    "Guard",
    "GuardRequest",
    "Incident",
    "Invoice",
    "RequestStatus",
    "Role",
    "Sector",
    "ShamoosVerificationLog",
    "Shift",
    "SLAPenalty",
    "User",
]
