"""Internationalization: locale resolution, message catalogs and helpers.

The active locale is resolved per request by `LocaleMiddleware` from the
`Accept-Language` header (or a `?lang=` query override) and stored in a
ContextVar, so any code on the request path can call `t("some.key")`.
"""
import json
from contextvars import ContextVar, Token
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Union
from urllib.parse import parse_qs

from starlette.datastructures import MutableHeaders
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings

LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"
DEFAULT_LOCALE: str = settings.DEFAULT_LOCALE
SUPPORTED_LOCALES = tuple(settings.SUPPORTED_LOCALES)

_current_locale: ContextVar[str] = ContextVar("current_locale", default=DEFAULT_LOCALE)


def get_locale() -> str:
    return _current_locale.get()


def set_locale(locale: str) -> Token:
    return _current_locale.set(locale if locale in SUPPORTED_LOCALES else DEFAULT_LOCALE)


# ---------------------------------------------------------------------------
# Locale negotiation
# ---------------------------------------------------------------------------
def parse_accept_language(header: Optional[str]) -> Optional[str]:
    """Return the best supported locale from an Accept-Language header, honouring q-values."""
    if not header:
        return None
    candidates = []
    for index, part in enumerate(header.split(",")):
        piece = part.strip()
        if not piece:
            continue
        tag, _, params = piece.partition(";")
        quality = 1.0
        for param in params.split(";"):
            param = param.strip()
            if param.startswith("q="):
                try:
                    quality = float(param[2:])
                except ValueError:
                    quality = 0.0
        candidates.append((quality, -index, tag.strip().lower()))

    for quality, _, tag in sorted(candidates, reverse=True):
        if quality <= 0:
            continue
        if tag == "*":
            return DEFAULT_LOCALE
        primary = tag.split("-")[0]
        if primary in SUPPORTED_LOCALES:
            return primary
    return None


def resolve_locale(accept_language: Optional[str], query_lang: Optional[str] = None) -> str:
    if query_lang and query_lang.lower() in SUPPORTED_LOCALES:
        return query_lang.lower()
    return parse_accept_language(accept_language) or DEFAULT_LOCALE


def locale_from_request(conn: HTTPConnection) -> str:
    """Locale for code running outside the ContextVar scope (e.g. top-level error handlers)."""
    state_locale = conn.scope.get("state", {}).get("locale")
    if state_locale:
        return state_locale
    return resolve_locale(conn.headers.get("accept-language"), conn.query_params.get("lang"))


# ---------------------------------------------------------------------------
# Message catalogs
# ---------------------------------------------------------------------------
@lru_cache(maxsize=None)
def load_catalog(locale: str) -> Dict[str, Any]:
    path = LOCALES_DIR / f"{locale}.json"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _lookup(catalog: Mapping[str, Any], key: str) -> Optional[str]:
    node: Any = catalog
    for part in key.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, str) else None


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def has_translation(key: str, locale: Optional[str] = None) -> bool:
    return _lookup(load_catalog(locale or get_locale()), key) is not None


def t(key: str, locale: Optional[str] = None, **params: Any) -> str:
    """Translate a dotted message key, falling back to the default locale, then the key itself."""
    locale = locale or get_locale()
    template = _lookup(load_catalog(locale), key)
    if template is None and locale != DEFAULT_LOCALE:
        template = _lookup(load_catalog(DEFAULT_LOCALE), key)
    if template is None:
        return key
    return template.format_map(_SafeDict(params))


def localize(value: Union[Mapping[str, str], str, None], locale: Optional[str] = None) -> Optional[str]:
    """Pick the right language out of a `{"en": ..., "ar": ...}` JSON column value."""
    if value is None or isinstance(value, str):
        return value
    locale = locale or get_locale()
    return value.get(locale) or value.get(DEFAULT_LOCALE) or next(iter(value.values()), None)


def enum_label(group: str, value: Union[Enum, str], locale: Optional[str] = None) -> str:
    code = value.value if isinstance(value, Enum) else str(value)
    key = f"enums.{group}.{code}"
    return t(key, locale) if has_translation(key, DEFAULT_LOCALE) else code


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
class LocaleMiddleware:
    """Pure ASGI middleware: resolves the request locale and sets `Content-Language`."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
        locale = resolve_locale(headers.get("accept-language"), (query.get("lang") or [None])[0])
        scope.setdefault("state", {})["locale"] = locale

        async def send_with_language(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                response_headers["Content-Language"] = locale
                response_headers.append("Vary", "Accept-Language")
            await send(message)

        token = set_locale(locale)
        try:
            await self.app(scope, receive, send_with_language)
        finally:
            _current_locale.reset(token)
