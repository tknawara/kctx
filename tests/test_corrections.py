"""Corrections plan/apply ordering fixtures (handover 8.4).

`retract` must not lose the correction operation: the durable correction
event (with its pending-review rows) is written against the pinned
pre-mutation state and before the target's own text is touched, so a failure
while updating the target leaves a visible, replayable operation, and
referrer discovery never sees the just-appended correction text.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corrections import all_paths, parse, retract  # noqa: E402
from errors import KctxError  # noqa: E402
from tests import _base  # noqa: E402


class RetractOrderingTest(_base.KctxTestCase):
    def test_correction_event_survives_target_append_failure(self):
        # A dossier target: the append goes through dossiers.load, which
        # raises if the dossier doesn't exist. Use an existing dossier so
        # only the *write* is made to fail.
        root = self.root
        (root / "inventory" / "assets").mkdir(parents=True)
        (root / "inventory" / "assets" / "a1.json").write_text(
            '{"id": "a1", "kind": "service", "name": "Asset One", '
            '"locator": "x", "owner": "o", "owner_source": "s", '
            '"schema_version": 1}',
            encoding="utf-8",
        )
        (root / "inventory" / "dossiers").mkdir(parents=True)
        (root / "inventory" / "dossiers" / "a1.md").write_text(
            "---\nasset: a1\nupdated: 2026-01-01\n---\n\n## Purpose\n\nDoes things.\n",
            encoding="utf-8",
        )

        real_write_text = Path.write_text

        def flaky(self, data, *a, **k):
            # Fail only the dossier write (after the correction record was
            # already written): the operation must not be lost.
            if self.name == "a1.md":
                raise OSError("disk simulated failure during target update")
            return real_write_text(self, data, *a, **k)

        with mock.patch.object(Path, "write_text", flaky):
            with self.assertRaises(OSError):
                retract(root, "a1", reason="no longer true", kind="dispute")

        # The correction event exists with the target's pending-review rows:
        # the operation is visible and recoverable, not lost.
        records = all_paths(root)
        self.assertEqual(len(records), 1)
        parsed = parse(records[0].read_text(encoding="utf-8"))
        self.assertEqual(parsed["frontmatter"]["target"], "a1")
        self.assertEqual(parsed["frontmatter"]["kind"], "dispute")
        # With no referrers the record carries the bounded no-referrers
        # marker; with referrers every row starts pending. Either way the
        # operation is recorded, not lost.
        if parsed["rows"]:
            self.assertEqual(parsed["rows"][0]["status"], "pending")
        else:
            body = records[0].read_text(encoding="utf-8")
            self.assertIn("no known referrers", body)

    def test_retract_writes_event_before_mutating_target(self):
        root = self.root
        (root / "inventory" / "assets").mkdir(parents=True)
        (root / "inventory" / "assets" / "a1.json").write_text(
            '{"id": "a1", "kind": "service", "name": "Asset One", '
            '"locator": "x", "owner": "o", "owner_source": "s", '
            '"schema_version": 1}',
            encoding="utf-8",
        )
        (root / "inventory" / "dossiers").mkdir(parents=True)
        dossier = root / "inventory" / "dossiers" / "a1.md"
        dossier.write_text(
            "---\nasset: a1\nupdated: 2026-01-01\n---\n\n## Purpose\n\nDoes things.\n",
            encoding="utf-8",
        )

        order = []
        real_write_text = Path.write_text

        def recording(self, data, *a, **k):
            if "corrections" in str(self):
                order.append("event")
            elif self.name == "a1.md":
                order.append("target")
            return real_write_text(self, data, *a, **k)

        with mock.patch.object(Path, "write_text", recording):
            result = retract(root, "a1", reason="superseded by b", kind="supersede")

        self.assertEqual(order, ["event", "target"])
        self.assertEqual(result["target_kind"], "dossier")
        # and the target carries the correction marker afterwards
        self.assertIn("## Corrections", dossier.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
