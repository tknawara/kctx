"""Shared error type for kctx.

Every command raises KctxError for expected failures (not found, malformed
records, stale inputs, write conflicts, incomplete evidence, permission and
timeout problems) so the CLI can report a stable category instead of a raw
traceback.
"""

CATEGORIES = {
    "not-found",
    "malformed",
    "stale",
    "conflict",
    "incomplete",
    "permission",
    "timeout",
}


class KctxError(Exception):
    def __init__(self, category: str, message: str):
        if category not in CATEGORIES:
            raise ValueError(f"unknown error category {category!r}")
        super().__init__(message)
        self.category = category
        self.message = message
