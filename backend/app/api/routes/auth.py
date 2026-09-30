from typing import Iterable, List

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_permissions
from app.core.exceptions import AppException
from app.core.permissions import ROLE_CREATION_MATRIX, Permission
from app.core.security import DUMMY_PASSWORD_HASH, create_access_token, hash_password, verify_password
from app.models import City, Facility, Firm, Guard, Role, Sector, User
from app.models.base import utcnow
from app.models.enums import RoleCode
from app.schemas.auth import (
    FacilityManagerRegister,
    FirmManagerRegister,
    LoginRequest,
    OAuthTokenOut,
    RegistrationOut,
    StaffCreate,
    TokenOut,
    UserOut,
)
from app.schemas.common import ERROR_RESPONSES, APIResponse, LabeledValue, ok

router = APIRouter(prefix="/auth", tags=["Authentication"], responses=ERROR_RESPONSES)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _ensure_email_free(db: Session, email: str) -> None:
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise AppException("auth.email_taken", status.HTTP_409_CONFLICT)


def _get_role(db: Session, code: RoleCode) -> Role:
    role = db.scalar(select(Role).where(Role.code == code))
    if role is None:
        raise AppException("auth.role_not_configured", status.HTTP_500_INTERNAL_SERVER_ERROR)
    return role


def _get_cities(db: Session, ids: Iterable[int]) -> List[City]:
    wanted = set(ids)
    cities = db.scalars(select(City).where(City.id.in_(wanted), City.is_active.is_(True))).all()
    if len(cities) != len(wanted):
        raise AppException("lookup.city_not_found", status.HTTP_422_UNPROCESSABLE_ENTITY)
    return list(cities)


def _authenticate(db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == email.lower()))
    if user is None:
        verify_password(password, DUMMY_PASSWORD_HASH)  # constant-time-ish: don't reveal unknown emails
        raise AppException("auth.invalid_credentials", status.HTTP_401_UNAUTHORIZED)
    if not verify_password(password, user.hashed_password):
        raise AppException("auth.invalid_credentials", status.HTTP_401_UNAUTHORIZED)
    if not user.is_active:
        raise AppException("auth.inactive_user", status.HTTP_401_UNAUTHORIZED)
    user.last_login_at = utcnow()
    db.commit()
    return user


# ---------------------------------------------------------------------------
# Registration (self sign-up for organisations)
# ---------------------------------------------------------------------------
@router.post("/register/firm", status_code=status.HTTP_201_CREATED, response_model=APIResponse[RegistrationOut])
def register_firm(payload: FirmManagerRegister, db: Session = Depends(get_db)):
    """Register a security firm and its Firm Manager. The firm starts as *pending* until a Super Admin approves it."""
    email = payload.email.lower()
    _ensure_email_free(db, email)
    data = payload.firm
    if db.scalar(select(Firm.id).where(Firm.moi_license_number == data.moi_license_number)):
        raise AppException("firm.license_taken", status.HTTP_409_CONFLICT)
    if data.commercial_registration and db.scalar(
        select(Firm.id).where(Firm.commercial_registration == data.commercial_registration)
    ):
        raise AppException("firm.cr_taken", status.HTTP_409_CONFLICT)

    cities = _get_cities(db, {data.headquarters_city_id, *data.operating_city_ids})
    firm = Firm(
        name=data.name,
        name_ar=data.name_ar,
        moi_license_number=data.moi_license_number,
        license_expiry_date=data.license_expiry_date,
        commercial_registration=data.commercial_registration,
        headquarters_city_id=data.headquarters_city_id,
        contact_email=data.contact_email,
        contact_phone=data.contact_phone,
        operating_cities=cities,
    )
    user = User(
        email=email,
        full_name=payload.full_name,
        phone=payload.phone,
        preferred_locale=payload.preferred_locale,
        hashed_password=hash_password(payload.password),
        role=_get_role(db, RoleCode.FIRM_MANAGER),
        firm=firm,
    )
    db.add_all([firm, user])
    db.commit()
    return ok(
        RegistrationOut(
            user=UserOut.from_model(user),
            organization_id=firm.id,
            organization_status=LabeledValue.of("firm_status", firm.status),
        ),
        "auth.firm_registered",
    )


@router.post("/register/facility", status_code=status.HTTP_201_CREATED, response_model=APIResponse[RegistrationOut])
def register_facility(payload: FacilityManagerRegister, db: Session = Depends(get_db)):
    """Register a client facility and its Facility Manager."""
    email = payload.email.lower()
    _ensure_email_free(db, email)
    data = payload.facility
    if db.get(Sector, data.sector_id) is None:
        raise AppException("lookup.sector_not_found", status.HTTP_422_UNPROCESSABLE_ENTITY)
    _get_cities(db, [data.city_id])

    facility = Facility(**data.model_dump())
    user = User(
        email=email,
        full_name=payload.full_name,
        phone=payload.phone,
        preferred_locale=payload.preferred_locale,
        hashed_password=hash_password(payload.password),
        role=_get_role(db, RoleCode.FACILITY_MANAGER),
        facility=facility,
    )
    db.add_all([facility, user])
    db.commit()
    return ok(
        RegistrationOut(user=UserOut.from_model(user), organization_id=facility.id),
        "auth.facility_registered",
    )


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
@router.post("/login", response_model=APIResponse[TokenOut])
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = _authenticate(db, payload.email, payload.password)
    token, expires_in = create_access_token(user.id, user.role.code.value)
    return ok(TokenOut(access_token=token, expires_in=expires_in, user=UserOut.from_model(user)), "auth.login_success")


@router.post("/token", response_model=OAuthTokenOut, summary="OAuth2 password flow (Swagger 'Authorize')")
def token(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = _authenticate(db, form.username, form.password)
    access_token, _ = create_access_token(user.id, user.role.code.value)
    return OAuthTokenOut(access_token=access_token)


@router.get("/me", response_model=APIResponse[UserOut])
def me(user: User = Depends(get_current_user)):
    return ok(UserOut.from_model(user))


# ---------------------------------------------------------------------------
# Staff accounts (created inside the creator's organisation)
# ---------------------------------------------------------------------------
@router.post("/users", status_code=status.HTTP_201_CREATED, response_model=APIResponse[UserOut])
def create_staff_user(
    payload: StaffCreate,
    db: Session = Depends(get_db),
    current: User = Depends(require_permissions(Permission.USER_MANAGE)),
):
    """Create HR/Dispatcher, Site Supervisor, Guard or platform staff accounts (see ROLE_CREATION_MATRIX)."""
    if payload.role not in ROLE_CREATION_MATRIX.get(current.role.code, frozenset()):
        raise AppException("auth.role_not_assignable", status.HTTP_403_FORBIDDEN)
    email = payload.email.lower()
    _ensure_email_free(db, email)

    user = User(
        email=email,
        full_name=payload.full_name,
        phone=payload.phone,
        preferred_locale=payload.preferred_locale,
        hashed_password=hash_password(payload.password),
        role=_get_role(db, payload.role),
        firm_id=current.firm_id,
        facility_id=current.facility_id,
    )

    if payload.guard_id is not None:
        guard = db.get(Guard, payload.guard_id)
        if (
            payload.role != RoleCode.SECURITY_GUARD
            or guard is None
            or guard.firm_id != current.firm_id
            or guard.user_id is not None
        ):
            raise AppException("auth.guard_link_invalid", status.HTTP_422_UNPROCESSABLE_ENTITY)
        guard.user = user

    db.add(user)
    db.commit()
    return ok(UserOut.from_model(user), "auth.user_created")
