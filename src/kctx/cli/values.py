"""Nominal value decoding at Click command boundaries."""

from collections.abc import Callable
from typing import TypeVar

from kctx.errors import KctxError

T = TypeVar("T")


def decode(name: str, value: str, constructor: Callable[[str], T]) -> T:
    try:
        return constructor(value)
    except ValueError as exc:
        raise KctxError("malformed", f"invalid {name}: {value!r}: {exc}") from exc


def optional(name: str, value: str | None, constructor: Callable[[str], T]) -> T | None:
    return None if value is None else decode(name, value, constructor)


def many(name: str, values: tuple[str, ...], constructor: Callable[[str], T]) -> tuple[T, ...]:
    return tuple(decode(name, value, constructor) for value in values)
