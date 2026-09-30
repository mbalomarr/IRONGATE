"""Localized error handling.

Every error response has the same envelope:
    {"success": false, "message": "<localized>", "code": "<stable key>", "errors": [...]}
"""
import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.i18n import has_translation, locale_from_request, t

logger = logging.getLogger(__name__)

_LOCATIONS = {"body", "query", "path", "header", "cookie"}
_STATUS_KEYS = {
    400: "common.bad_request",
    401: "common.unauthorized",
    403: "common.forbidden",
    404: "common.not_found",
    405: "common.method_not_allowed",
    409: "common.conflict",
    429: "common.too_many_requests",
}


class AppException(Exception):
    """Raise with a translation key; the handler renders it in the request's language."""

    def __init__(
        self,
        message_key: str,
        status_code: int = 400,
        *,
        params: Optional[Dict[str, Any]] = None,
        code: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(message_key)
        self.message_key = message_key
        self.status_code = status_code
        self.params = params or {}
        self.code = code or message_key
        self.headers = headers


def _error_body(message: str, code: str, errors: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {"success": False, "message": message, "code": code}
    if errors is not None:
        body["errors"] = errors
    return body


def _field_path(loc: Sequence[Any]) -> Optional[str]:
    parts = list(loc[1:]) if loc and loc[0] in _LOCATIONS else list(loc)
    return ".".join(str(p) for p in parts) or None


def _field_label(loc: Sequence[Any], locale: str) -> str:
    names = [p for p in (loc[1:] if loc and loc[0] in _LOCATIONS else loc) if isinstance(p, str)]
    if not names:
        return t("fields._self", locale)
    key = f"fields.{names[-1]}"
    return t(key, locale) if has_translation(key, locale) else names[-1]


def _simple_ctx(ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in ctx.items() if isinstance(v, (str, int, float, Decimal))}


def translate_validation_error(error: Dict[str, Any], locale: str) -> Dict[str, Any]:
    loc = error.get("loc", ())
    error_type = error.get("type", "")
    ctx = dict(error.get("ctx") or {})
    field = _field_label(loc, locale)

    if error_type == "i18n":  # raised via app.schemas.common.i18n_error
        key = ctx.pop("key")
    else:
        key = f"validation.{error_type}"
        if not has_translation(key, locale):
            key = "validation.default"
    return {
        "field": _field_path(loc),
        "message": t(key, locale, field=field, **_simple_ctx(ctx)),
        "type": error_type,
    }


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    locale = locale_from_request(request)
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_body(t(exc.message_key, locale, **exc.params), exc.code),
        headers=exc.headers,
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    locale = locale_from_request(request)
    if isinstance(exc.detail, str) and has_translation(exc.detail, locale):
        key = exc.detail
    else:
        key = _STATUS_KEYS.get(exc.status_code, "common.error")
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_body(t(key, locale), key),
        headers=getattr(exc, "headers", None),
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    locale = locale_from_request(request)
    errors = [translate_validation_error(err, locale) for err in exc.errors()]
    return JSONResponse(
        status_code=422,
        content=_error_body(t("common.validation_failed", locale), "common.validation_failed", errors),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    locale = locale_from_request(request)
    # 500s are rendered by Starlette's outermost ServerErrorMiddleware, i.e. *outside* CORSMiddleware.
    # Without this header the browser reports an opaque CORS failure instead of our localized message.
    headers = {"Access-Control-Allow-Origin": "*"} if "*" in settings.CORS_ORIGINS else None
    return JSONResponse(
        status_code=500,
        content=_error_body(t("common.internal_error", locale), "common.internal_error"),
        headers=headers,
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
