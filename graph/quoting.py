"""The one tested helper for putting a value into a `dolt sql -q` read query.

Writes never go through this: bulk upserts use `dolt table import` against a
CSV file (see dolt_store.DoltStore.replace_table/upsert_rows), which needs no
SQL string building at all. Only read queries (uses/impact/diff/check, plus
`AS OF <hash>` and `dolt_diff()` calls) interpolate a value into SQL text,
and every one of them must go through `sql_quote` here.
"""

import re

from errors import KctxError

# Defense in depth ahead of sql_quote's escaping: an id containing a raw
# quote, backslash, or newline is already suspicious for a graph node/edge
# id (none of the kb's id schemes -- ev:, sig:, inv:, proposal:, code:, a
# bare asset id, a URL -- legitimately need one), so reject it outright
# rather than rely solely on escaping to make it safe.
_UNSAFE_CHARS_RE = re.compile(r"['\\\x00\n\r]")


def validate_id(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise KctxError("malformed", f"expected a non-empty id string, got {value!r}")
    if _UNSAFE_CHARS_RE.search(value):
        raise KctxError(
            "malformed",
            f"id {value!r} contains a quote/backslash/newline, refusing to query it",
        )
    return value


def sql_quote(value) -> str:
    """Single-quote and escape a value for interpolation into a `dolt sql -q`
    string. None becomes the bare SQL keyword NULL."""
    if value is None:
        return "NULL"
    return "'" + str(value).replace("\\", "\\\\").replace("'", "''") + "'"
