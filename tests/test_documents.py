from dataclasses import FrozenInstanceError

from _base import KctxTestCase
from test_proposals import _add

from kctx.codecs.documents import parse_document, read_document
from kctx.codecs.frontmatter import read_frontmatter
from kctx.codecs.proposals import decode_proposal
from kctx.domain.ids import GateId
from kctx.domain.vocabulary import GateOutcome, ProposalOrigin, ProposalStatus
from kctx.errors import KctxError
from kctx.services import proposals


class LosslessDocumentTest(KctxTestCase):
    def test_field_update_preserves_unaffected_bytes_and_crlf(self):
        original = "---\r\nid: x\r\nstatus : proposed  \r\ncustom: opaque # comment\r\n---\r\n\r\n# Title\r\n\r\n## Context\r\n\r\nkeep  spaces\r\n\r\n## Unknown\r\n```markdown\r\n## Context\r\n```\r\n"
        document = parse_document(original)
        self.assertEqual(tuple(document.sections), ("Context", "Unknown"))
        updated = document.update_fields({"status": "accepted"})
        self.assertEqual(updated.text, original.replace("status : proposed", "status : accepted"))
        path = self.root / "record.md"
        updated.write(path)
        self.assertEqual(read_document(path).text, updated.text)
        self.assertEqual(path.read_bytes(), updated.text.encode())

    def test_section_replacement_preserves_unknown_sections_and_spacing(self):
        original = "---\ncustom: yes\n---\n# T\n\n## Context\n\nold\n\n\n## User notes\n\nopaque  \n"
        updated = parse_document(original).update_section("Context", "new")
        self.assertEqual(updated.text, original.replace("\nold\n", "\nnew\n"))

    def test_log_append_preserves_authored_bytes(self):
        original = "---\r\nid: x\r\n---\r\n# T\r\n## Decision log\r\n\r\n- old  text\r\n\r\n## Unknown\r\n\r\nleave alone\r\n"
        updated = parse_document(original).append_section("Decision log", "- new")
        self.assertEqual(updated.text, original.replace("- old  text", "- old  text\r\n- new"))

    def test_fences_do_not_create_sections_or_table_rows(self):
        document = parse_document("---\nid: x\n---\n## Context\n````md\n## Fake\n```\n## Also fake\n````\n~~~\n## Hidden\n~~~\n## Actual\nreal\n")
        self.assertEqual(tuple(document.sections), ("Context", "Actual"))
        self.assertNotIn("## Fake", document.unfenced_lines())

    def test_duplicate_keys_and_headings_are_diagnosed(self):
        for raw in ("---\nid: x\nid: y\n---\n", "---\nid: x\n---\n## Context\na\n## Context\nb\n"):
            with self.subTest(raw=raw), self.assertRaises(KctxError):
                parse_document(raw)
        with self.assertRaises(KctxError):
            read_frontmatter("---\nid: x\nid: y\n---\n")

    def test_drafts_parse_separately_from_admission(self):
        draft = parse_document("---\ntitle: unfinished\n---\n## Research\n")
        self.assertEqual(draft.frontmatter["title"], "unfinished")
        with self.assertRaises(KctxError):
            decode_proposal(draft)
        with self.assertRaises(KctxError):
            parse_document(draft.text, required_keys=("id",))
        with self.assertRaises(KctxError):
            parse_document(draft.text, required_sections=("Decision log",))

    def test_document_views_are_immutable(self):
        document = parse_document("---\nid: x\n---\n## Context\nx\n")
        with self.assertRaises(TypeError):
            document.frontmatter["id"] = "y"
        with self.assertRaises(FrozenInstanceError):
            document.text = "changed"


class ProposalDocumentBoundaryTest(KctxTestCase):
    def test_status_gate_and_field_edits_preserve_custom_authored_content(self):
        added = _add(self.root)
        raw = added.path.read_text().replace("---\n", "---\ncustom: retain me\n", 1)
        raw = raw.replace("## Decision log", "## Unknown section\n\n```markdown\n## Context\n```\n\n## Decision log")
        raw = raw.replace("\n", "\r\n")
        added.path.write_bytes(raw.encode())
        proposals.set_status(self.root, added.id, origin=ProposalOrigin.STEWARD)
        changed = added.path.read_bytes().decode()
        self.assertEqual(changed, raw.replace("origin: user-request", "origin: steward"))
        proposals.set_status(self.root, added.id, status=ProposalStatus.ACCEPTED, by="user")
        proposals.gate(self.root, added.id, GateId("G1"), outcome=GateOutcome.PASS, evidence="obs:1", checker="fixture-checker", expires_at=4102444800, by="agent")
        final = added.path.read_bytes().decode()
        self.assertIn("custom: retain me\r\n", final)
        self.assertIn("## Unknown section\r\n\r\n```markdown\r\n## Context\r\n```\r\n", final)
        self.assertNotIn("\n", final.replace("\r\n", ""))

    def test_malformed_frontmatter_fails_before_mutation(self):
        added = _add(self.root)
        original = added.path.read_text()
        for old, replacement in (("status: proposed", "status: imaginary"), ("kind: config", "kind: invented"), ("origin: user-request", "origin: invalid"), ("type: ", "type: imaginary"), ("references: []", "references: not-a-list"), ("---\n", "---\nschema_version: 999\n")):
            broken = original.replace(old, replacement, 1)
            added.path.write_text(broken)
            with self.subTest(replacement=replacement), self.assertRaises(KctxError):
                proposals.set_status(self.root, added.id, origin=ProposalOrigin.OTHER)
            self.assertEqual(added.path.read_text(), broken)

    def test_duplicate_log_blocks_gate_history_mutation(self):
        added = _add(self.root)
        original_results = (added.path.parent / "gates.json").read_bytes()
        added.path.write_text(added.path.read_text() + "\n## Decision log\nambiguous\n")
        with self.assertRaises(KctxError):
            proposals.gate(self.root, added.id, GateId("G1"), outcome=GateOutcome.PASS, evidence="obs:1", checker="fixture-checker", expires_at=4102444800, by="agent")
        self.assertEqual((added.path.parent / "gates.json").read_bytes(), original_results)
