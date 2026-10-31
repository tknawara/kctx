"""Golden non-code construction and safe human-readable rendering fixtures."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kctx.citations.construction import make_other, make_proposal
from kctx.citations.models import CitationStatus, Classification
from kctx.citations.rendering import extract_cite_items, redact_text, render_one
from kctx.config import Config
from kctx.errors import KctxError

SEEN = "2026-10-31T12:00Z"


class CitationConstructionTests(unittest.TestCase):
    def test_golden_make_other_kinds(self) -> None:
        fixtures: tuple[tuple[str, dict[str, str], str], ...] = (
            ("commit", {"repo": "org/repo", "rev": "abc123"}, "kind=commit repo=org/repo rev=abc123 seen=2026-10-31T12:00Z ttl=none"),
            ("pr", {"repo": "org/repo", "n": "42", "q": "gh pr view 42"}, 'kind=pr repo=org/repo n=42 q="gh pr view 42" seen=2026-10-31T12:00Z ttl=3d'),
            ("ticket", {"id": "DRQS123", "q": "ticket show"}, 'kind=ticket id=DRQS123 q="ticket show" seen=2026-10-31T12:00Z ttl=3d'),
            ("breg", {"name": "flag", "env": "prod", "q": "breg get"}, 'kind=breg name=flag env=prod q="breg get" seen=2026-10-31T12:00Z ttl=1d'),
            ("deploy", {"service": "api", "env": "prod", "q": "deploy show"}, 'kind=deploy service=api env=prod q="deploy show" seen=2026-10-31T12:00Z ttl=1d'),
            ("query", {"sys": "sql", "q": "select 1"}, 'kind=query sys=sql q="select 1" seen=2026-10-31T12:00Z ttl=none'),
            ("doc", {"url": "https://example.test", "section": "intro", "q": "curl url"}, 'kind=doc url=https://example.test section=intro q="curl url" seen=2026-10-31T12:00Z ttl=30d'),
            ("web", {"url": "https://example.test", "q": "curl url"}, 'kind=web url=https://example.test q="curl url" seen=2026-10-31T12:00Z ttl=30d'),
            ("usr", {"date": "2026-10-31", "where": "review call"}, 'kind=usr date=2026-10-31 where="review call" seen=2026-10-31T12:00Z ttl=none'),
            ("ev", {"id": "incident/evidence"}, "kind=ev id=incident/evidence seen=2026-10-31T12:00Z ttl=none"),
            ("gate", {"proposal": "p", "gate": "G01", "outcome": "unk", "rev": "org/repo@abcdef0"}, "kind=gate proposal=p gate=G01 outcome=unk rev=org/repo@abcdef0 seen=2026-10-31T12:00Z ttl=none"),
            ("record", {"path": "assets/api.md", "state": "active"}, "kind=record path=assets/api.md state=active seen=2026-10-31T12:00Z ttl=none"),
        )
        for kind, fields, body in fixtures:
            with self.subTest(kind=kind):
                made = make_other(kind, {**fields, "seen": SEEN})
                self.assertEqual(made.line, f"⟦cite {body}⟧")
                self.assertNotIn("kind", fields)

    def test_query_aliases_and_extensions(self) -> None:
        for alias, system in (("metric", "guts"), ("log", "humio"), ("data", "sql")):
            made = make_other(alias, {"q": "query", "seen": SEEN, "custom": "µ"})
            self.assertEqual(made.fields["kind"], "query")
            self.assertEqual(made.fields["sys"], system)
            self.assertTrue(made.line.endswith("custom=µ⟧"))
        self.assertEqual(make_other("metric", {"q": "query", "sys": "custom"}).fields["sys"], "custom")

    def test_required_fields_sensitivity_and_gate_outcomes(self) -> None:
        for kind, fields in (
            ("web", {"url": "https://example.test"}), ("deploy", {"env": "prod", "q": "query"}),
            ("usr", {"date": "2026-10-31", "where": "call", "sens": "secret"}),
            ("gate", {"proposal": "p", "gate": "g", "outcome": "unknown", "rev": "abc"}),
            ("code", {}),
        ):
            with self.subTest(kind=kind), self.assertRaises(KctxError):
                make_other(kind, fields)

    def test_proposal_live_state_defaults_and_evidence_render(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = Config(root=root)
            (root / "proposals").mkdir()
            path = root / "proposals" / "p.md"
            for state, ttl in (("draft", "7d"), ("verified", "none"), ("rejected", "none"), ("superseded", "none")):
                path.write_text(f"---\nstatus: {state}\n---\nproposal\n", encoding="utf-8")
                made = make_proposal("p", config=config)
                self.assertEqual(made.fields["state"], state)
                self.assertEqual(made.fields["ttl"], ttl)
            self.assertEqual(make_proposal("p", "2d", config=config).fields["ttl"], "2d")
            with self.assertRaises(KctxError):
                make_proposal("missing", config=config)
            (root / "incident" / "evidence").mkdir(parents=True)
            (root / "incident" / "evidence" / "sample.md").write_text("---\nsource: captured trace\n---\nline one\nline two\n", encoding="utf-8")
            rendered = render_one({"kind": "ev", "id": "incident/sample"}, config=config)
            self.assertIn("source: captured trace", rendered)
            self.assertIn("line one\nline two", rendered)


class CitationRenderingTests(unittest.TestCase):
    def test_every_kind_and_legacy_query_alias(self) -> None:
        config = Config(github_host="git.example.test")
        fixtures: tuple[tuple[dict[str, str], str], ...] = (
            ({"kind": "code", "repo": "org/repo", "rev": "abc", "path": "a.py", "L": "2-4", "sym": "f"}, "https://git.example.test/org/repo/blob/abc/a.py#L2-L4 — (f)"),
            ({"kind": "commit", "repo": "org/repo", "rev": "abc"}, "https://git.example.test/org/repo/commit/abc"),
            ({"kind": "pr", "repo": "org/repo", "n": "42", "state": "open"}, "https://git.example.test/org/repo/pull/42 (open)"),
            ({"kind": "ticket", "id": "drqs123"}, "{DRQS 123}"),
            ({"kind": "doc", "url": "https://docs.test", "section": "intro", "quote": "hello"}, 'https://docs.test#intro — "hello"'),
            ({"kind": "web", "url": "https://web.test"}, "https://web.test"),
            ({"kind": "query", "sys": "sql", "q": "select 1", "seen": SEEN, "rows": "1", "window": "1h", "ev": "report"}, "sql query run 2026-10-31T12:00Z over 1h: `select 1` → 1 rows; results: report"),
            ({"kind": "metric", "q": "query", "seen": SEEN, "result": "ok"}, "metric query run 2026-10-31T12:00Z: `query` → ok"),
            ({"kind": "log", "q": "query"}, "log query run : `query` → (no summary recorded)"),
            ({"kind": "data", "q": "query"}, "data query run : `query` → (no summary recorded)"),
            ({"kind": "usr", "who": "Zoë", "date": "2026-10-31", "quote": "yes"}, 'Zoë said on 2026-10-31: "yes"'),
            ({"kind": "breg", "name": "flag", "env": "prod", "value": "on", "seen": SEEN}, "BREG flag [prod] = on (as of 2026-10-31T12:00Z)"),
            ({"kind": "deploy", "service": "api", "env": "prod", "version": "v1", "seen": SEEN}, "api [prod] = v1 (as of 2026-10-31T12:00Z)"),
            ({"kind": "proposal", "id": "p", "state": "draft", "seen": SEEN}, "proposal p (draft as of 2026-10-31T12:00Z)"),
            ({"kind": "gate", "proposal": "p", "gate": "g", "outcome": "pass", "rev": "abc"}, "gate g of proposal p: pass at abc"),
            ({"kind": "record", "path": "assets/api.md", "state": "active", "seen": SEEN}, "record assets/api.md (active as of 2026-10-31T12:00Z)"),
        )
        for fields, expected in fixtures:
            with self.subTest(kind=fields["kind"]):
                self.assertEqual(render_one(fields, config=config), expected)

    def test_code_check_statuses(self) -> None:
        fields = {"kind": "code", "repo": "org/repo", "rev": "abc", "path": "a.py", "L": "1-1", "seen": SEEN}
        fixtures = (
            (Classification(CitationStatus.FRESH), "verified fresh"),
            (Classification(CitationStatus.MOVED, line_range="4-4"), "moved to L=4-4"),
            (Classification(CitationStatus.CHANGED), "logic changed since"),
            (Classification(CitationStatus.GONE), "path no longer exists"),
            (Classification(CitationStatus.UNVERIFIABLE, reason="offline"), "could not verify (offline)"),
        )
        for status, expected in fixtures:
            with patch("kctx.citations.rendering.classify_code", return_value=status):
                self.assertIn(expected, render_one(fields, do_check=True, config=Config()))

    def test_plain_markdown_slack_and_escaped_html(self) -> None:
        fields = {"kind": "web", "url": "https://web.test/?a=1&b=2", "quote": "<script>alert(1)</script>"}
        url = fields["url"]
        self.assertIn(f"[{url}]({url})", render_one(fields, "md", config=Config()))
        self.assertIn(f"<{url}>", render_one(fields, "slack", config=Config()))
        html = render_one(fields, "html", config=Config())
        self.assertIn('<a href="https://web.test/?a=1&amp;b=2">', html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>", html)
        self.assertNotIn("<a ", render_one({"kind": "web", "url": "javascript:alert(1)"}, "html", config=Config()))
        self.assertIn("&lt;b&gt;", render_one({"kind": "usr", "quote": "<b>"}, "html", config=Config()))

    def test_visibility_and_secrets(self) -> None:
        fields = {"kind": "usr", "quote": "password=abc token=def Authorization: Bearer xyz", "sens": "restricted"}
        self.assertEqual(render_one(fields, audience="external", config=Config()), "[internal reference withheld]")
        self.assertEqual(render_one(fields, config=Config()), "[restricted — use --unredacted to view]")
        rendered = render_one(fields, unredacted=True, config=Config())
        for secret in ("abc", "def", "xyz"):
            self.assertNotIn(secret, rendered)
        self.assertEqual(redact_text("account:foo secret=bar api_key=baz AKIA0123456789ABCDEF", "account"), "account:‹redacted› secret=‹redacted› api_key=‹redacted› ‹redacted›")
        self.assertEqual(redact_text("private 123", "regex:[0-9]+"), "private ‹redacted›")
        with self.assertRaises(KctxError):
            redact_text("value", "regex:[")

    def test_multiple_literal_tokens_and_file_target(self) -> None:
        text = "⟦cite kind=web url=https://a.test⟧ and ⟦cite kind=ticket id=DRQS1⟧"
        self.assertEqual(len(extract_cite_items(text)), 2)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "note.md"
            path.write_text(text, encoding="utf-8")
            self.assertEqual(extract_cite_items(str(path)), extract_cite_items(text))
        with self.assertRaises(KctxError):
            extract_cite_items("⟦cite no closing delimiter")
