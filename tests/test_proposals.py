import json

from _base import KctxTestCase

import gates as gates_mod
import proposals
import storage
from errors import KctxError

GATES_TABLE_LAND = (
    "| id | claim | check | when | by |\n"
    "|---|---|---|---|---|\n"
    "| G1 | it works | `true` | land | agent |\n"
)
GATES_TABLE_FULL = (
    "| id | claim | check | when | by |\n"
    "|---|---|---|---|---|\n"
    "| G1 | lands clean | `true` | land | agent |\n"
    "| G2 | deployed | `curl -f x` | deploy | agent |\n"
    "| G3 | used once | `grep x log` | use | user |\n"
)
TWO_ALTERNATIVES = "- A. do nothing\n- B. do the thing\n"


def _add(root, **overrides):
    kwargs = dict(
        kind="config",
        origin="user-request",
        title="Add a widget",
        context="ctx",
        evidence="ev",
        change="chg",
        why="why",
        research="researched internally and externally",
        alternatives=TWO_ALTERNATIVES,
        gates=GATES_TABLE_FULL,
    )
    kwargs.update(overrides)
    return proposals.add(root, **kwargs)


class SplitCommasTest(KctxTestCase):
    def test_split_commas_respecting_brackets(self):
        test_cases = [
            # Balanced quotes: track quotes normally.
            ('x, "y, z"', ['"y, z"', 'x']),  # order may vary with strip+sort
            # Unbalanced quotes: don't track quotes, split on every comma outside ⟦…⟧.
            ('a "b, c', ['a "b', 'c']),
            ('x, "y, z', ['x', '"y', 'z']),
            # Brackets respected even with unbalanced quotes.
            ('a, ⟦cite x="y, z"⟧', ['a', '⟦cite x="y, z"⟧']),
            # Balanced quotes with brackets.
            ('x, ⟦cite y="z, w"⟧', ['x', '⟦cite y="z, w"⟧']),
        ]
        for raw, expected in test_cases:
            with self.subTest(raw=raw):
                result = storage.split_commas_respecting_brackets(raw)
                # Sort both for stable comparison since strip+sort may reorder.
                self.assertEqual(sorted(result), sorted(expected))


class ProposalFilingTest(KctxTestCase):
    def test_add_creates_directory_home_with_full_sections(self):
        added = _add(self.root)
        self.assertTrue(added["path"].endswith("add-a-widget/proposal.md"))
        self.assertEqual(added["frontmatter"]["status"], "proposed")
        self.assertNotIn("missing", added)

        home = self.root / "proposals" / "config" / f"{proposals.today()}-add-a-widget"
        self.assertTrue((home / "research").is_dir())
        self.assertTrue((home / "evidence").is_dir())
        self.assertEqual(json.loads((home / "gates.json").read_text()), [])

        rows = proposals.list_proposals(self.root)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["origin"], "user-request")

    def test_add_missing_sections_is_filed_as_draft(self):
        added = _add(self.root, research="", alternatives="", gates="")
        self.assertEqual(added["frontmatter"]["status"], "draft")
        self.assertEqual(len(added["missing"]), 3)

        self.assertEqual(proposals.list_proposals(self.root, status="proposed"), [])
        self.assertEqual(len(proposals.list_proposals(self.root, status="draft")), 1)

    def test_one_line_research_skip_counts_as_present(self):
        added = _add(self.root, research="typo fix; nothing to research")
        self.assertEqual(added["frontmatter"]["status"], "proposed")
        self.assertNotIn("missing", added)

    def test_type_as_list_round_trips(self):
        added = _add(self.root, type=["agent", "module"], title="Cross cutting")
        fm = proposals.load(self.root, added["id"])["frontmatter"]
        self.assertEqual(fm["type"], ["agent", "module"])

    def test_type_as_single_string_round_trips(self):
        added = _add(self.root, type="agent", title="Single type")
        fm = proposals.load(self.root, added["id"])["frontmatter"]
        self.assertEqual(fm["type"], "agent")

    def test_reference_cite_with_comma_in_quoted_field_round_trips_as_one_item(self):
        cite = '⟦cite kind=code repo=org/repo rev=x path=p.py L=1-2 blob=b span=s sym="a, b"⟧'
        added = _add(self.root, references=[cite], title="Cited ref")
        fm = proposals.load(self.root, added["id"])["frontmatter"]
        self.assertEqual(fm["references"], [cite])

    def test_bad_origin_rejected(self):
        with self.assertRaises(KctxError) as ctx:
            _add(self.root, origin="not-a-real-origin")
        self.assertEqual(ctx.exception.category, "malformed")

    def test_idempotent_add_conflict_then_force(self):
        _add(self.root, title="Dup idea", kind="other")
        with self.assertRaises(KctxError) as ctx:
            _add(self.root, title="Dup idea", kind="other", context="c2")
        self.assertEqual(ctx.exception.category, "conflict")

        forced = _add(
            self.root, title="Dup idea", kind="other", context="c3", force=True
        )
        body = proposals.load(self.root, forced["id"])["body"]
        self.assertEqual(body["Context"], "c3")


class LegacyLayoutTest(KctxTestCase):
    """A proposal filed before the directory-home layout existed: a single
    proposals/<kind>/<date>-<slug>.md file with only the original five
    sections. Every command must read it in place, never migrate it."""

    def _write_legacy(self, status="proposed", decided_by=None, extra_log=""):
        kind_dir = proposals.proposals_root(self.root) / "skill"
        kind_dir.mkdir(parents=True, exist_ok=True)
        path = kind_dir / "2026-10-01-legacy-thing.md"
        fm = {
            "id": "skill/2026-10-01-legacy-thing",
            "kind": "skill",
            "type": "skill-refinement",
            "title": "Legacy thing",
            "status": status,
            "created": "2026-10-01",
            "updated": "2026-10-01",
            "target": [],
            "references": [],
            "decided_by": decided_by,
            "superseded_by": None,
        }
        body = {
            "Context": "c",
            "Evidence": "e",
            "Proposed change": "ch",
            "Why general / justification": "w",
            "Decision log": f"- 2026-10-01: {status}" + extra_log,
        }
        path.write_text(proposals.render(fm, body), encoding="utf-8")
        return path

    def test_legacy_file_is_listed_and_loaded(self):
        self._write_legacy()
        rows = proposals.list_proposals(self.root)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "skill/2026-10-01-legacy-thing")

        found = proposals.load(self.root, "skill/2026-10-01-legacy-thing")
        self.assertEqual(
            set(found["body"].keys()),
            {
                "Context",
                "Evidence",
                "Proposed change",
                "Why general / justification",
                "Decision log",
            },
        )

    def test_legacy_file_keeps_its_shape_after_a_status_change(self):
        path = self._write_legacy()
        proposals.set_status(
            self.root, "skill/2026-10-01-legacy-thing", status="accepted", by="user"
        )
        text = path.read_text(encoding="utf-8")
        self.assertNotIn("## Research", text)
        self.assertNotIn("## Acceptance gates", text)
        self.assertIn("## Decision log", text)

    def test_legacy_proposal_without_gates_table_lands_with_warning(self):
        self._write_legacy(status="landing", decided_by="user")
        fm = proposals.set_status(
            self.root, "skill/2026-10-01-legacy-thing", status="applied", by="user"
        )
        self.assertEqual(fm["status"], "applied")
        self.assertTrue(any("legacy" in w for w in fm.get("warnings", [])))

    def test_gates_json_for_legacy_proposal_is_a_sibling_file(self):
        self._write_legacy(status="landing", decided_by="user")
        proposals.set_status(
            self.root, "skill/2026-10-01-legacy-thing", status="applied", by="user"
        )
        path = proposals.load(self.root, "skill/2026-10-01-legacy-thing")["path"]
        gp = gates_mod.gates_json_path(path)
        self.assertEqual(gp.name, "2026-10-01-legacy-thing.gates.json")


class LifecycleTransitionTest(KctxTestCase):
    def _to_landing(self, title="Flow"):
        added = _add(self.root, title=title, gates=GATES_TABLE_LAND)
        pid = added["id"]
        proposals.set_status(self.root, pid, status="accepted", by="user")
        proposals.set_status(self.root, pid, status="landing", by="agent")
        return pid

    def test_full_happy_path(self):
        pid = self._to_landing()
        with self.assertRaises(KctxError) as ctx:
            proposals.set_status(self.root, pid, status="applied", by="agent")
        self.assertEqual(ctx.exception.category, "incomplete")

        proposals.gate(self.root, pid, "G1", outcome="pass", evidence="obs:1")
        fm = proposals.set_status(self.root, pid, status="applied", by="agent")
        self.assertEqual(fm["status"], "applied")
        self.assertNotIn("warnings", fm)

    def test_draft_to_proposed_requires_readiness(self):
        # Intentional contract change (handover 8.1): draft -> proposed must
        # clear the same review gate as filing directly as proposed. The old
        # bypass — any draft could be promoted bare — is gone.
        added = _add(self.root, research="", alternatives="", gates="")
        self.assertEqual(added["frontmatter"]["status"], "draft")
        with self.assertRaises(KctxError) as ctx:
            proposals.set_status(self.root, added["id"], status="proposed")
        self.assertEqual(ctx.exception.category, "incomplete")
        self.assertIn("missing for review", str(ctx.exception))

    def test_ready_draft_promotes_to_proposed(self):
        # A draft whose sections are later filled in promotes cleanly: the
        # readiness predicate is the same review gate, evaluated on the
        # candidate body at promotion time.
        added = _add(self.root, research="", alternatives="", gates="")
        self.assertEqual(added["frontmatter"]["status"], "draft")
        path = proposals.load(self.root, added["id"])["path"]
        text = path.read_text()
        text = text.replace(
            "## Research\n", "## Research\nlooked at three options\n", 1
        ).replace(
            "## Alternatives considered\n",
            "## Alternatives considered\n" + TWO_ALTERNATIVES + "\n",
            1,
        ).replace(
            "## Acceptance gates\n",
            "## Acceptance gates\n" + GATES_TABLE_FULL + "\n",
            1,
        )
        path.write_text(text)
        fm = proposals.set_status(self.root, added["id"], status="proposed")
        self.assertEqual(fm["status"], "proposed")

    def test_illegal_transition_skips_landing(self):
        added = _add(self.root, gates=GATES_TABLE_LAND)
        proposals.set_status(self.root, added["id"], status="accepted", by="user")
        with self.assertRaises(KctxError) as ctx:
            proposals.set_status(self.root, added["id"], status="applied", by="user")
        self.assertEqual(ctx.exception.category, "malformed")

    def test_illegal_transition_from_proposed_to_verified(self):
        added = _add(self.root)
        with self.assertRaises(KctxError) as ctx:
            proposals.set_status(self.root, added["id"], status="verified", by="user")
        self.assertEqual(ctx.exception.category, "malformed")

    def test_same_status_transition_rejected(self):
        added = _add(self.root)
        with self.assertRaises(KctxError) as ctx:
            proposals.set_status(self.root, added["id"], status="proposed")
        self.assertEqual(ctx.exception.category, "malformed")

    def test_superseded_reachable_from_any_status(self):
        added = _add(self.root)
        proposals.set_status(self.root, added["id"], status="rejected", by="user")
        fm = proposals.set_status(
            self.root, added["id"], status="superseded", superseded_by="other/id"
        )
        self.assertEqual(fm["status"], "superseded")
        self.assertEqual(fm["superseded_by"], "other/id")

    def test_landing_requires_by(self):
        added = _add(self.root, gates=GATES_TABLE_LAND)
        proposals.set_status(self.root, added["id"], status="accepted", by="user")
        with self.assertRaises(KctxError) as ctx:
            proposals.set_status(self.root, added["id"], status="landing")
        self.assertEqual(ctx.exception.category, "incomplete")

    def test_regressed_requires_note(self):
        pid = self._to_landing()
        proposals.gate(self.root, pid, "G1", outcome="pass", evidence="obs:1")
        proposals.set_status(self.root, pid, status="applied", by="agent")
        with self.assertRaises(KctxError) as ctx:
            proposals.set_status(self.root, pid, status="regressed", by="user")
        self.assertEqual(ctx.exception.category, "incomplete")

        fm = proposals.set_status(
            self.root, pid, status="regressed", by="user", note="use gate G2 failed"
        )
        self.assertEqual(fm["status"], "regressed")

    def test_verified_requires_deploy_and_use_gates(self):
        added = _add(self.root, title="Deploy flow", gates=GATES_TABLE_FULL)
        pid = added["id"]
        proposals.set_status(self.root, pid, status="accepted", by="user")
        proposals.set_status(self.root, pid, status="landing", by="agent")
        proposals.gate(self.root, pid, "G1", outcome="pass", evidence="obs:1")
        proposals.set_status(self.root, pid, status="applied", by="agent")

        with self.assertRaises(KctxError):
            proposals.set_status(self.root, pid, status="verified", by="user")

        proposals.gate(self.root, pid, "G2", outcome="pass", evidence="obs:2")
        with self.assertRaises(KctxError):
            proposals.set_status(self.root, pid, status="verified", by="user")

        proposals.gate(self.root, pid, "G3", outcome="pass", evidence="obs:3")
        fm = proposals.set_status(self.root, pid, status="verified", by="user")
        self.assertEqual(fm["status"], "verified")

    def test_set_fields_only_update_without_status(self):
        added = _add(self.root)
        fm = proposals.set_status(self.root, added["id"], origin="steward")
        self.assertEqual(fm["origin"], "steward")
        self.assertEqual(fm["status"], "proposed")

    def test_set_with_nothing_to_do_is_incomplete(self):
        added = _add(self.root)
        with self.assertRaises(KctxError) as ctx:
            proposals.set_status(self.root, added["id"])
        self.assertEqual(ctx.exception.category, "incomplete")

    def test_landed_add_dedupes(self):
        added = _add(self.root)
        fm = proposals.set_status(
            self.root, added["id"], landed_add=["dotfiles@abc1234"]
        )
        fm = proposals.set_status(
            self.root,
            added["id"],
            landed_add=["dotfiles@abc1234", "projects@def5678"],
        )
        self.assertEqual(fm["landed"], ["dotfiles@abc1234", "projects@def5678"])


class GateTest(KctxTestCase):
    def test_gate_unknown_id_rejected(self):
        added = _add(self.root, gates=GATES_TABLE_LAND)
        with self.assertRaises(KctxError) as ctx:
            proposals.gate(
                self.root, added["id"], "G99", outcome="pass", evidence="obs:1"
            )
        self.assertEqual(ctx.exception.category, "not-found")

    def test_gate_appends_to_gates_json_and_decision_log(self):
        added = _add(self.root, gates=GATES_TABLE_LAND)
        proposals.gate(
            self.root, added["id"], "G1", outcome="pass", evidence="obs:1", by="agent"
        )
        found = proposals.load(self.root, added["id"])
        results = gates_mod.load_results(found["path"])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["gate"], "G1")
        self.assertEqual(results[0]["outcome"], "pass")
        self.assertIn("G1 -> pass", found["body"]["Decision log"])

    def test_pending_gates_listing(self):
        added = _add(self.root, title="Pending flow", gates=GATES_TABLE_FULL)
        pid = added["id"]
        proposals.set_status(self.root, pid, status="accepted", by="user")
        proposals.set_status(self.root, pid, status="landing", by="agent")
        proposals.gate(self.root, pid, "G1", outcome="pass", evidence="obs:1")
        proposals.set_status(self.root, pid, status="applied", by="agent")

        pending = proposals.list_proposals(self.root, pending_gates=True)
        self.assertEqual(len(pending), 1)
        self.assertEqual(set(pending[0]["pending_gates"]), {"G2", "G3"})

        proposals.gate(self.root, pid, "G2", outcome="pass", evidence="obs:2")
        proposals.gate(self.root, pid, "G3", outcome="pass", evidence="obs:3")
        self.assertEqual(proposals.list_proposals(self.root, pending_gates=True), [])


class ShowTest(KctxTestCase):
    def test_show_reports_frontmatter_sections_and_gate_status(self):
        added = _add(self.root, gates=GATES_TABLE_FULL)
        proposals.gate(self.root, added["id"], "G1", outcome="pass", evidence="obs:1")

        shown = proposals.show(self.root, added["id"])
        self.assertEqual(shown["id"], added["id"])
        self.assertIn("Acceptance gates", shown["sections"])
        by_id = {g["id"]: g for g in shown["gates"]}
        self.assertEqual(by_id["G1"]["outcome"], "pass")
        self.assertEqual(by_id["G2"]["outcome"], "unk")


class BackfillLandedTest(KctxTestCase):
    def test_backfills_landed_from_decision_log_token(self):
        added = _add(self.root, gates=GATES_TABLE_LAND)
        path = proposals.load(self.root, added["id"])["path"]
        text = path.read_text(encoding="utf-8").replace(
            "status: proposed", "status: applied", 1
        )
        text = text.rstrip() + "\n- 2026-10-24: applied by user — dotfiles@e72e37d\n"
        path.write_text(text, encoding="utf-8")

        changed = proposals.backfill_landed_from_notes(self.root)
        self.assertEqual(len(changed), 1)
        fm = proposals.load(self.root, added["id"])["frontmatter"]
        self.assertEqual(fm["landed"], ["dotfiles@e72e37d"])

        # idempotent: already-backfilled proposals are left alone.
        self.assertEqual(proposals.backfill_landed_from_notes(self.root), [])

    def test_dry_run_does_not_write(self):
        added = _add(self.root, gates=GATES_TABLE_LAND)
        path = proposals.load(self.root, added["id"])["path"]
        text = path.read_text(encoding="utf-8").replace(
            "status: proposed", "status: applied", 1
        )
        text = text.rstrip() + "\n- 2026-10-24: applied — scratch@cc25b6f\n"
        path.write_text(text, encoding="utf-8")

        changed = proposals.backfill_landed_from_notes(self.root, dry_run=True)
        self.assertEqual(len(changed), 1)
        fm = proposals.load(self.root, added["id"])["frontmatter"]
        self.assertEqual(fm["landed"], [])

    def test_no_token_leaves_landed_empty(self):
        added = _add(self.root, gates=GATES_TABLE_LAND)
        path = proposals.load(self.root, added["id"])["path"]
        text = path.read_text(encoding="utf-8").replace(
            "status: proposed", "status: applied", 1
        )
        path.write_text(text, encoding="utf-8")

        changed = proposals.backfill_landed_from_notes(self.root)
        self.assertEqual(changed, [])
