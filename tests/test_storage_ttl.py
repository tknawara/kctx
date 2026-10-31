"""Boundary fixtures for the is_past_ttl -> semantics-core cutover (M5).

The inclusive-boundary convention (`observed <= now <= observed + ttl` is
fresh; one second past is stale) is a compatibility contract with the Lean
`assessFresh` (formal/Kctx/Time.lean, T11) and the agent-facing `kctx stale`.
"""

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kctx.domain.time import is_past_ttl, ttl_seconds


class TtlBoundaryTests(unittest.TestCase):
    def test_none_and_missing_ttl_never_stale(self):
        at = "2026-01-01T00:00:00Z"
        self.assertIsNone(ttl_seconds(None))
        self.assertIsNone(ttl_seconds("none"))
        self.assertFalse(is_past_ttl(at, None))
        self.assertFalse(is_past_ttl(at, "none"))

    def test_inclusive_boundary_is_fresh(self):
        at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        # exactly observed + ttl -> NOT past ttl (inclusive boundary)
        self.assertFalse(is_past_ttl("2026-01-01T00:00:00Z", "1h", at + timedelta(hours=1)))

    def test_one_second_past_boundary_is_stale(self):
        at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.assertTrue(
            is_past_ttl("2026-01-01T00:00:00Z", "1h", at + timedelta(hours=1, seconds=1))
        )

    def test_days_and_hours_units(self):
        at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.assertEqual(ttl_seconds("2d"), 2 * 86400)
        self.assertEqual(ttl_seconds("3h"), 3 * 3600)
        self.assertFalse(is_past_ttl("2026-01-01T00:00:00Z", "1d", at + timedelta(hours=23)))
        self.assertTrue(is_past_ttl("2026-01-01T00:00:00Z", "1d", at + timedelta(days=1, seconds=1)))

    def test_bare_date_observation_is_accepted(self):
        at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        # civil date means midnight UTC for this comparison
        self.assertFalse(is_past_ttl("2026-01-01", "1d", at))


if __name__ == "__main__":
    unittest.main()
