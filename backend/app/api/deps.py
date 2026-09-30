"""Shared FastAPI dependencies: DB session, current user, RBAC guards, locale."""
from typing import Callable, Optional

import jwt
from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AppException
from app.core.i18n import locale_from_request
from app.core.permissions import Permission, has_permissions
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_PREFIX}/auth/token", auto_error=False)
_BEARER = {"WWW-Authenticate": "Bearer"}

__all__ = ["get_db", "get_current_user", "require_permissions", "get_request_locale"]


def get_request_locale(request: Request) -> str:
    """Inject the negotiated locale ("en" / "ar") into an endpoint."""
    return locale_from_request(request)


def get_current_user(token: Optional[str] = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    if not token:
        raise AppException("common.unauthorized", 401, headers=_BEARER)
    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise AppException("auth.token_expired", 401, headers=_BEARER)
    except jwt.PyJWTError:
        raise AppException("auth.token_invalid", 401, headers=_BEARER)

    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        raise AppException("auth.token_invalid", 401, headers=_BEARER)

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise AppException("auth.inactive_user", 401, headers=_BEARER)
    return user


def require_permissions(*permissions: Permission, any_of: bool = False) -> Callable[..., User]:
    """Dependency factory: `user = Depends(require_permissions(Permission.BID_SUBMIT))`."""

    def dependency(user: User = Depends(get_current_user)) -> User:
        if not has_permissions(user.role.code, permissions, any_of=any_of):
            raise AppException("common.forbidden", 403)
        return user

    return dependency
