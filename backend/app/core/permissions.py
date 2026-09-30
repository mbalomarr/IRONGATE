"""RBAC matrix: which role may do what.

Roles live in the `roles` table (for localized names / portal assignment);
the role -> permission mapping is kept in code so it is versioned and reviewed
alongside the endpoints that enforce it.
"""
from enum import Enum
from typing import Dict, FrozenSet, Iterable

from app.models.enums import RoleCode


class Permission(str, Enum):
    # Platform
    FIRM_REVIEW = "firms:review"
    REVENUE_VIEW = "platform:revenue"
    SLA_MANAGE = "sla:manage"
    REQUEST_MONITOR = "requests:monitor"
    SHAMOOS_MONITOR = "shamoos:monitor"
    # Shared
    USER_MANAGE = "users:manage"
    REQUEST_VIEW = "requests:view"
    CONTRACT_VIEW = "contracts:view"
    INVOICE_VIEW = "invoices:view"
    # Security firm
    BID_SUBMIT = "bids:submit"
    CONTRACT_SIGN = "contracts:sign"
    GUARD_VIEW = "guards:view"
    GUARD_MANAGE = "guards:manage"
    SHAMOOS_VERIFY = "shamoos:verify"
    SHIFT_ASSIGN = "shifts:assign"
    # Client
    REQUEST_CREATE = "requests:create"
    BID_COMPARE = "bids:compare"
    BID_AWARD = "bids:award"
    CONTRACT_APPROVE = "contracts:approve"
    INVOICE_PAY = "invoices:pay"
    GEOFENCE_ALERTS = "geofence:alerts"
    INCIDENT_REVIEW = "incidents:review"
    # Guard mobile app
    SHIFT_CLOCK = "shifts:clock"
    SHIFT_VIEW_OWN = "shifts:view_own"
    INCIDENT_REPORT = "incidents:report"


P = Permission

ROLE_PERMISSIONS: Dict[RoleCode, FrozenSet[Permission]] = {
    RoleCode.SUPER_ADMIN: frozenset(Permission),
    # Operations: monitoring only, deliberately no financial permissions.
    RoleCode.OPERATIONS: frozenset({P.REQUEST_MONITOR, P.REQUEST_VIEW, P.SHAMOOS_MONITOR}),
    RoleCode.FIRM_MANAGER: frozenset(
        {P.USER_MANAGE, P.REQUEST_VIEW, P.BID_SUBMIT, P.CONTRACT_SIGN, P.CONTRACT_VIEW, P.INVOICE_VIEW, P.GUARD_VIEW}
    ),
    RoleCode.HR_DISPATCHER: frozenset(
        {P.USER_MANAGE, P.REQUEST_VIEW, P.GUARD_VIEW, P.GUARD_MANAGE, P.SHAMOOS_VERIFY, P.SHIFT_ASSIGN}
    ),
    RoleCode.FACILITY_MANAGER: frozenset(
        {
            P.USER_MANAGE, P.REQUEST_VIEW, P.REQUEST_CREATE, P.BID_COMPARE, P.BID_AWARD,
            P.CONTRACT_APPROVE, P.CONTRACT_VIEW, P.INVOICE_VIEW, P.INVOICE_PAY, P.GEOFENCE_ALERTS,
        }
    ),
    RoleCode.SITE_SUPERVISOR: frozenset({P.REQUEST_VIEW, P.GEOFENCE_ALERTS, P.INCIDENT_REVIEW}),
    RoleCode.SECURITY_GUARD: frozenset({P.SHIFT_CLOCK, P.SHIFT_VIEW_OWN, P.INCIDENT_REPORT}),
}

# Which roles each role may create via POST /auth/users (new user joins the creator's organization).
ROLE_CREATION_MATRIX: Dict[RoleCode, FrozenSet[RoleCode]] = {
    RoleCode.SUPER_ADMIN: frozenset({RoleCode.SUPER_ADMIN, RoleCode.OPERATIONS}),
    RoleCode.FIRM_MANAGER: frozenset({RoleCode.HR_DISPATCHER, RoleCode.SECURITY_GUARD}),
    RoleCode.HR_DISPATCHER: frozenset({RoleCode.SECURITY_GUARD}),
    RoleCode.FACILITY_MANAGER: frozenset({RoleCode.SITE_SUPERVISOR}),
}

PLATFORM_ROLES = frozenset({RoleCode.SUPER_ADMIN, RoleCode.OPERATIONS})
FIRM_ROLES = frozenset({RoleCode.FIRM_MANAGER, RoleCode.HR_DISPATCHER})
CLIENT_ROLES = frozenset({RoleCode.FACILITY_MANAGER, RoleCode.SITE_SUPERVISOR})


def has_permissions(role: RoleCode, permissions: Iterable[Permission], any_of: bool = False) -> bool:
    granted = ROLE_PERMISSIONS.get(role, frozenset())
    required = list(permissions)
    return any(p in granted for p in required) if any_of else all(p in granted for p in required)
