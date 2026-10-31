"""Filesystem primitives shared by every kctx module: root resolution, atomic
and exclusive JSON writes, hashing, and small formatting helpers.
"""

import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import List, Optional

# M5 cutover slice: is_past_ttl routes through the proved semantics core
# (kctx.semantics.time mirrors formal/Kctx/Time.lean, T11). The public
# contract (signature, inclusive boundary, missing TTL = never stale) is
# unchanged; see tests/test_storage_ttl.py for boundary fixtures.
_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from errors import KctxError


def find_root() -> Path:
    """Resolve the knowledge workspace root.

    KCTX_ROOT wins when set (this is how tests isolate themselves). Otherwise
    walk up from this file's own location looking for a .git directory, so
    the tool works the same regardless of the caller's cwd.
    """
    env = os.environ.get("KCTX_ROOT")
    if env:
        return Path(env).resolve()
    here = Path(__file__).resolve().parent
    for candidate in [here, *here.parents]:
        if (candidate / ".git").exists():
            return candidate
    raise KctxError(
        "not-found",
        "could not locate repo root (no .git found above tools/kctx and KCTX_ROOT is unset)",
    )


def read_json(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise KctxError("not-found", f"{path} not found")
    except json.JSONDecodeError as e:
        raise KctxError("malformed", f"{path}: invalid JSON ({e})")


def atomic_write_json(path: Path, data: dict) -> None:
    """Write via a temp file in the same directory, then os.replace.

    A crash mid-write leaves an orphaned .tmp-* file next to the target, not
    a half-written target, and callers that list *.json never see it.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, str(path))
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def exclusive_write_json(path: Path, data: dict) -> None:
    """Claim path atomically (O_CREAT|O_EXCL) and write JSON into it.

    Used for observation records: they are immutable and append-only, so two
    concurrent writers racing on the same id must have exactly one winner.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        raise KctxError("conflict", f"{path} already exists")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())


def list_json_files(dir_path: Path) -> List[Path]:
    if not dir_path.exists():
        return []
    return sorted(p for p in dir_path.glob("*.json"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "item"


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def compact_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def today() -> str:
    return date.today().isoformat()


def parse_flexible_timestamp(value: str) -> datetime:
    """Accept either a bare date (YYYY-MM-DD) or a full iso_now()-style
    timestamp; a bare date is treated as midnight UTC."""
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        raise KctxError("malformed", f"bad timestamp {value!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


TTL_RE = re.compile(r"^(\d+)([dh])$")


def ttl_seconds(ttl: Optional[str]) -> Optional[int]:
    if not ttl or ttl == "none":
        return None
    m = TTL_RE.match(ttl)
    if not m:
        raise KctxError(
            "malformed", f"bad ttl {ttl!r}, expected '<N>d', '<N>h', or 'none'"
        )
    n, unit = int(m.group(1)), m.group(2)
    return n * (3600 if unit == "h" else 86400)


def is_past_ttl(
    verified_at: str, ttl: Optional[str], now: Optional[datetime] = None
) -> bool:
    secs = ttl_seconds(ttl)
    if secs is None:
        return False
    now = now or datetime.now(timezone.utc)
    from kctx.semantics.model import Ttl
    from kctx.semantics.time import Freshness, assess_fresh

    verdict = assess_fresh(
        Ttl("expireAfter", secs),
        int(parse_flexible_timestamp(verified_at).timestamp()),
        int(now.timestamp()),
    )
    return verdict is Freshness.STALE


def read_frontmatter(text: str) -> dict:
    """Parse a flat `key: value` frontmatter block delimited by `---` lines,
    without interpreting any value's syntax (a bracketed list stays a raw
    string; pair with split_list_value for that). Returns {} when the text
    doesn't open with a frontmatter block at all -- callers treat that as
    nothing to check, not malformed."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fm: dict = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return fm


def split_commas_respecting_brackets(raw: str) -> List[str]:
    """Split on top-level commas, treating a `⟦...⟧` durable citation or a
    double-quoted span as opaque -- a comma inside either (e.g. a cite's
    `sym="a, b"`) doesn't start a new list item. If the raw value has an odd
    number of quote characters, quotes are not tracked (to prevent a stray
    quote from swallowing commas); only ⟦...⟧ are respected in that case."""
    items: List[str] = []
    buf: List[str] = []
    depth = 0
    # Check for balanced quotes: if odd number, don't track quotes.
    quote_count = raw.count('"')
    in_quotes = False if quote_count % 2 == 0 else None
    for ch in raw:
        if ch == '"' and in_quotes is not None:
            in_quotes = not in_quotes
            buf.append(ch)
        elif ch == "⟦" and (in_quotes is None or not in_quotes):
            depth += 1
            buf.append(ch)
        elif ch == "⟧" and (in_quotes is None or not in_quotes):
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch == "," and depth == 0 and (in_quotes is None or not in_quotes):
            items.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    items.append("".join(buf))
    return [x.strip() for x in items if x.strip()]


def split_list_value(raw: str) -> List[str]:
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    return split_commas_respecting_brackets(raw)
