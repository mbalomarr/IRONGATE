"""Domain enums. Values are persisted; localized labels live in locales/*.json under `enums.*`."""
from enum import Enum


class RoleCode(str, Enum):
    SUPER_ADMIN = "super_admin"
    OPERATIONS = "operations"
    FIRM_MANAGER = "firm_manager"
    HR_DISPATCHER = "hr_dispatcher"
    FACILITY_MANAGER = "facility_manager"
    SITE_SUPERVISOR = "site_supervisor"
    SECURITY_GUARD = "security_guard"


class Portal(str, Enum):
    PLATFORM = "platform"
    FIRM = "firm"
    CLIENT = "client"
    MOBILE = "mobile"


class FirmStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUSPENDED = "suspended"


class ShamoosStatus(str, Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


class ShamoosCheckResult(str, Enum):
    VERIFIED = "verified"
    REJECTED = "rejected"
    ERROR = "error"


class EmploymentStatus(str, Enum):
    ACTIVE = "active"
    ON_LEAVE = "on_leave"
    TERMINATED = "terminated"


class RequestStatusCode(str, Enum):
    """Codes of the `request_statuses` lookup table (labels are stored there as JSON)."""

    OPEN = "open"
    AWARDED = "awarded"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class BidStatus(str, Enum):
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class ContractStatus(str, Enum):
    PENDING_FIRM_SIGNATURE = "pending_firm_signature"
    PENDING_FACILITY_APPROVAL = "pending_facility_approval"
    ACTIVE = "active"
    COMPLETED = "completed"
    TERMINATED = "terminated"


class ShiftStatus(str, Enum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    MISSED = "missed"
    CANCELLED = "cancelled"


class IncidentSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentStatus(str, Enum):
    OPEN = "open"
    UNDER_REVIEW = "under_review"
    RESOLVED = "resolved"


class InvoiceStatus(str, Enum):
    DRAFT = "draft"
    ISSUED = "issued"
    PAID = "paid"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"


class PenaltyStatus(str, Enum):
    PENDING = "pending"  # waiting for an open (draft) invoice
    APPLIED = "applied"
    WAIVED = "waived"
