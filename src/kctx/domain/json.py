"""JSON-only wire values and explicit boundary validation."""

from __future__ import annotations

import math
from enum import Enum
from typing import TypeAlias, TypeGuard, TypeVar

from kctx.errors import KctxError

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
_E = TypeVar("_E", bound=Enum)


def _object_list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _object_dict(value: object) -> TypeGuard[dict[object, object]]:
    return isinstance(value, dict)


def json_value(value: object, field: str = "value") -> JsonValue:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if _object_list(value):
        return [json_value(item, field) for item in value]
    if _object_dict(value):
        result: JsonObject = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise KctxError("malformed", f"{field} requires string keys")
            result[key] = json_value(item, f"{field}.{key}")
        return result
    raise KctxError("malformed", f"{field} must contain only JSON values")


def object_value(value: object, field: str = "record") -> JsonObject:
    checked = json_value(value, field)
    if not isinstance(checked, dict):
        raise KctxError("malformed", f"{field} must be an object")
    return checked


def fields(
    value: object,
    *,
    required: set[str],
    optional: set[str] | frozenset[str] = frozenset(),
    versioned: bool = True,
) -> JsonObject:
    data = object_value(value)
    missing = required - data.keys()
    unknown = data.keys() - required - optional - ({"schema_version"} if versioned else set())
    if missing or unknown:
        raise KctxError(
            "malformed", f"record fields: missing={sorted(missing)}, unknown={sorted(unknown)}"
        )
    if versioned:
        version = data.get("schema_version", 1)
        if type(version) is not int or version != 1:
            raise KctxError("malformed", f"unsupported schema_version {version!r}")
    return data


def text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise KctxError("malformed", f"{field} must be a string")
    return value


def optional_text(value: object, field: str) -> str | None:
    return None if value is None else text(value, field)


def texts(value: object, field: str) -> tuple[str, ...]:
    if not _object_list(value):
        raise KctxError("malformed", f"{field} must be an array")
    return tuple(text(item, field) for item in value)


def enum_value(enum: type[_E], value: object, field: str) -> _E:
    raw = text(value, field)
    try:
        return enum(raw)
    except ValueError as exc:
        raise KctxError("malformed", f"invalid {field}: {raw!r}") from exc


def optional_bool(value: object, field: str) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    raise KctxError("malformed", f"{field} must be a boolean or null")


def integer(value: object, field: str) -> int:
    if type(value) is not int:
        raise KctxError("malformed", f"{field} must be an integer")
    return value
