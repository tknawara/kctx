"""Explicit CLI design/binding commands and migration are externally usable."""

import io
import json
from contextlib import redirect_stdout
from hashlib import sha256

from _base import KctxTestCase
from test_authored_design import LEGACY_DESIGN
from test_proposals import GATES_TABLE_LAND, TWO_ALTERNATIVES

from kctx.cli import app


def _command(*arguments):
    stream = io.StringIO()
    with redirect_stdout(stream):
        code = app.main(["--json", "proposal", *arguments])
    return code, json.loads(stream.getvalue())


class AuthoredDesignCliTest(KctxTestCase):
    def test_long_inline_gate_table_is_content_not_a_path(self):
        claim = "The reviewed implementation preserves the declared contract. " * 20
        table = (
            "| id | claim | check | when | by | checker |\n"
            "|---|---|---|---|---|---|\n"
            f"| G1 | {claim} | inspect implementation | land | reviewer | fixture-checker |\n"
        )
        code, added = _command(
            "add", "--kind", "config", "--origin", "user-request", "--title", "Long gate",
            "--context", "c", "--evidence", "e", "--change", "ch", "--why", "w",
            "--research", "Reviewed", "--alternatives", TWO_ALTERNATIVES,
            "--gates", table, "--environment", "test", "--scope", "implementation",
            "--target-source", str(self.root / "future-implementation.txt"),
        )
        self.assertEqual(code, 0)
        self.assertEqual(added["frontmatter"]["status"], "proposed")
        code, accepted = _command("set", added["id"], "--status", "accepted", "--by", "designer")
        self.assertEqual(code, 0)
        self.assertIsNone(accepted["target_revision"])

    def test_design_add_bind_and_reopen_use_explicit_source_and_file_cas(self):
        source = self.root / "implementation.txt"
        code, added = _command(
            "add", "--kind", "config", "--origin", "user-request", "--title", "Design first",
            "--context", "c", "--evidence", "e", "--change", "ch", "--why", "w",
            "--research", "Reviewed", "--alternatives", TWO_ALTERNATIVES,
            "--gates", GATES_TABLE_LAND, "--environment", "test", "--scope", "implementation",
            "--target-source", str(source),
        )
        self.assertEqual(code, 0)
        identity = added["id"]
        self.assertEqual(added["frontmatter"]["workflow_version"], 3)
        self.assertIsNone(added["frontmatter"]["target_revision"])
        code, accepted = _command("set", identity, "--status", "accepted", "--by", "designer")
        self.assertEqual(code, 0)
        self.assertFalse(source.exists())
        code, shown = _command("show", identity)
        self.assertEqual(code, 0)
        source.write_text("implementation")
        target = f"{source}@sha256:{sha256(source.read_bytes()).hexdigest()}"
        code, bound = _command("bind", identity, "--target-revision", target, "--by", "implementer", "--expected-revision", shown["revision"])
        self.assertEqual(code, 0)
        self.assertEqual(bound["binding"]["source"], str(source))
        self.assertEqual(bound["accepted_revision"], accepted["accepted_revision"])
        code, failure = _command("reopen", identity, "--by", "designer", "--note", "Renew review", "--expected-revision", shown["revision"])
        self.assertEqual(code, 1)
        self.assertEqual(failure["error"], "conflict")
        code, reopened = _command("reopen", identity, "--by", "designer", "--note", "Renew review")
        self.assertEqual(code, 0)
        self.assertEqual(reopened["status"], "proposed")
        self.assertIsNone(reopened["binding"])
        self.assertIsNone(reopened["accepted_revision"])
        code, changed = _command("set", identity, "--target-source", str(self.root / "other.txt"))
        self.assertEqual(code, 0)
        self.assertEqual(changed["target_source"], str(self.root / "other.txt"))

    def test_legacy_adoption_is_explicit_and_renews_acceptance(self):
        path = self.root / "proposals/config/legacy/proposal.md"
        path.parent.mkdir(parents=True)
        path.write_text(LEGACY_DESIGN)
        original = path.read_bytes()
        code, failure = _command("set", "config/legacy", "--status", "accepted", "--by", "designer")
        self.assertEqual(code, 1)
        self.assertEqual(path.read_bytes(), original)
        code, adopted = _command("adopt", "config/legacy", "--by", "designer", "--note", "New review", "--target-source", "./future.txt")
        self.assertEqual(code, 0)
        self.assertEqual(adopted["workflow_version"], 3)
        self.assertIsNone(adopted["accepted_revision"])
        code, accepted = _command("set", "config/legacy", "--status", "accepted", "--by", "new-designer")
        self.assertEqual(failure["error"], "incomplete")
        self.assertEqual(code, 0)
        self.assertEqual(accepted["acceptor"], "new-designer")
