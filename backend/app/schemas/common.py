"""Shared response envelope and schema helpers."""
import re
from enum import Enum
from typing import Any, Dict, Generic, List, Optional, TypeVar, Union

from pydantic import BaseModel
from pydantic_core import PydanticCustomError

from app.core.i18n import enum_label, t

T = TypeVar("T")

SAUDI_MOBILE_PATTERN = r"^(\+9665|05)\d{8}$"
_NATIONAL_ID_RE = re.compile(r"^[12]\d{9}$")


class APIResponse(BaseModel, Generic[T]):
    """Standard success envelope. `message` is localized per Accept-Language."""

    success: bool = True
    message: str
    data: Optional[T] = None


class Page(BaseModel, Generic[T]):
    items: List[T]
    total: int
    limit: int
    offset: int


class ErrorItem(BaseModel):
    field: Optional[str] = None
    message: str
    type: str


class ErrorResponse(BaseModel):
    success: bool = False
    message: str
    code: str
    errors: Optional[List[ErrorItem]] = None


class LabeledValue(BaseModel):
    """An enum/status value with its localized label, e.g. {"code": "verified", "label": "تم التحقق"}."""

    code: str
    label: str

    @classmethod
    def of(cls, group: str, value: Union[Enum, str]) -> "LabeledValue":
        code = value.value if isinstance(value, Enum) else str(value)
        return cls(code=code, label=enum_label(group, code))


class NamedRef(BaseModel):
    id: int
    name: str


def ok(data: Any = None, message_key: str = "common.success", **params: Any) -> Dict[str, Any]:
    return {"success": True, "message": t(message_key, **params), "data": data}


def i18n_error(key: str, **params: Any) -> PydanticCustomError:
    """Raise from validators to get a fully localized validation message for `key`."""
    return PydanticCustomError("i18n", key, {"key": key, **params})


def validate_national_id(value: str) -> str:
    value = value.strip()
    if not _NATIONAL_ID_RE.match(value):
        raise i18n_error("shamoos.invalid_national_id")
    return value


ERROR_RESPONSES: Dict[Union[int, str], Dict[str, Any]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}
