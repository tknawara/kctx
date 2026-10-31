"""Stdlib-only output redaction, never applied to stored source evidence.

These helpers remove recognizable credentials while retaining diagnostic context.
They cannot identify an arbitrary secret that has no label or recognizable format.
"""

import re
from collections.abc import Mapping, Sequence
from typing import TypeGuard
from urllib.parse import unquote_plus, urlsplit, urlunsplit

REDACTED = "\u2039redacted\u203a"
_KEY = (
    r"(?:password|passwd|pwd|(?:access[_-]?|refresh[_-]?|id[_-]?|auth[_-]?|api[_-]?)?token"
    r"|(?:proxy[_-]?)?authorization|(?:x[_-]?)?api[_-]?key"
    r"|(?:client[_-]?|access[_-]?)?secret(?:[_-]?(?:access[_-]?)?key)?"
    r"|(?:aws[_-]?)?(?:secret[_-]?)?access[_-]?key(?:[_-]?id)?"
    r"|private[_-]?key|credentials?|(?:set[_-]?)?cookie)"
)
_QUOTED_VALUE = r'"(?:\\.|[^"\\])*"' + "|" + r"'(?:\\.|[^'\\])*'"
_VALUE = rf"(?:{_QUOTED_VALUE}|[^\s,;&}}\]\"']+)"
_ASSIGNMENT = re.compile(
    rf"(?P<prefix>(?<![\w-])[\"']?{_KEY}[\"']?\s*[:=]\s*)(?P<value>{_VALUE})",
    re.IGNORECASE,
)
_AUTHORIZATION = re.compile(
    rf"(?P<prefix>(?<![\w-])[\"']?(?:proxy[_-]?)?authorization[\"']?\s*[:=]\s*)"
    rf"(?P<value>{_QUOTED_VALUE}|(?:Bearer|Basic)\s+[^\s,;\"']+|[^\s,;\"']+)",
    re.IGNORECASE,
)
_FLAG = re.compile(
    rf"(?P<prefix>--?{_KEY}(?:=|\s+|[\"']\s*,\s*))(?P<value>{_VALUE})",
    re.IGNORECASE,
)
_PEM = re.compile(
    r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----.*?-----END (?:[A-Z0-9]+ )*PRIVATE KEY-----",
    re.DOTALL,
)
_AWS_KEY = re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")
_URL = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s<>\"']+")
_SECRET_NAME = re.compile(rf"{_KEY}", re.IGNORECASE)


def is_secret_key(key: str) -> bool:
    return _SECRET_NAME.fullmatch(key.strip().lstrip("-")) is not None


def _masked_value(match: re.Match[str]) -> str:
    value = match.group("value")
    if value.startswith(('"', "'")) and value.endswith(value[0]):
        return match.group("prefix") + value[0] + REDACTED + value[0]
    return match.group("prefix") + REDACTED


def _mask_url(match: re.Match[str]) -> str:
    raw = match.group(0)
    try:
        url = urlsplit(raw)
    except ValueError:
        # Malformed authorities still must not expose userinfo credentials.
        return re.sub(r"(://)[^/\s]*@", rf"\1{REDACTED}@", raw)
    netloc = url.netloc
    if "@" in netloc:
        netloc = REDACTED + "@" + netloc.rsplit("@", 1)[1]
    parts: list[str] = []
    for part in url.query.split("&"):
        name, separator, value = part.partition("=")
        parts.append(
            name
            + separator
            + (REDACTED if separator and is_secret_key(unquote_plus(name)) else value)
        )
    return urlunsplit((url.scheme, netloc, url.path, "&".join(parts), url.fragment))


def mask_secrets(text: str) -> str:
    """Mask labeled text/JSON credentials, URL secrets, private keys and flags."""
    text = _PEM.sub(REDACTED, text)
    text = _URL.sub(_mask_url, text)
    text = _AUTHORIZATION.sub(_masked_value, text)
    text = _ASSIGNMENT.sub(_masked_value, text)
    text = _FLAG.sub(_masked_value, text)
    return _AWS_KEY.sub(REDACTED, text)


def scrub_argv(argv: Sequence[str]) -> list[str]:
    """Keep command shape, but hide separate values of credential flags."""
    result: list[str] = []
    secret_next = False
    for arg in argv:
        if secret_next:
            result.append(REDACTED)
            secret_next = False
            continue
        result.append(mask_secrets(arg))
        secret_next = arg.startswith("-") and "=" not in arg and is_secret_key(arg)
    return result


def _mapping(value: object) -> TypeGuard[Mapping[object, object]]:
    return isinstance(value, Mapping)


def _sequence(value: object) -> TypeGuard[list[object] | tuple[object, ...]]:
    return isinstance(value, (list, tuple))


def _strings(value: Sequence[object]) -> TypeGuard[Sequence[str]]:
    return all(isinstance(item, str) for item in value)


def scrub(value: object) -> object:
    """Return a detached, JSON-friendly redacted view of structured diagnostics."""
    if isinstance(value, str):
        return mask_secrets(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if _mapping(value):
        return {
            mask_secrets(str(key)): REDACTED if is_secret_key(str(key)) else scrub(item)
            for key, item in value.items()
        }
    if _sequence(value):
        if _strings(value):
            return scrub_argv(value)
        return [scrub(item) for item in value]
    return mask_secrets(str(value))
