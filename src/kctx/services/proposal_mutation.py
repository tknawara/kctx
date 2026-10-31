"""Recoverable proposal-document/gate-history publication under one record lock.

This journal makes an interrupted cooperating write completable, not a claim
of multi-file atomic visibility. Readers recover under the same proposal lock.
It confers no knowledge-release or signature authority.
"""

import json
from pathlib import Path

from kctx.adapters.files.mutations import (
    FileRevision,
    atomic_write_bytes,
    compare_and_write,
    fsync_directory,
    read_revision,
    revision_of,
)
from kctx.adapters.files.storage import read_json
from kctx.codecs.documents import parse_document
from kctx.codecs.gates import decode_gate_result, encode_gate_result
from kctx.codecs.proposals import decode_proposal
from kctx.domain.json import fields, json_value, text
from kctx.domain.proposals import GateResult, ProposalDocument
from kctx.errors import KctxError
from kctx.services.gates import gates_json_path


def _journal_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.kctx-mutation.json")


def recover(path: Path) -> None:
    """Caller holds file_lock(path); replay only matching old/new predecessors."""
    journal = _journal_path(path)
    if not journal.exists():
        return
    record = fields(
        read_json(journal),
        required={"document", "expected_document", "gates", "expected_gates"},
        versioned=False,
    )
    document = text(record["document"], "document").encode("utf-8")
    expected = FileRevision(text(record["expected_document"], "expected_document"))
    decode_proposal(parse_document(document.decode("utf-8")))
    current = read_revision(path)
    if current not in (expected, revision_of(document)):
        raise KctxError("conflict", f"{path} changed during interrupted proposal publication")
    gates_value = record["gates"]
    if gates_value is not None:
        content = text(gates_value, "gates").encode("utf-8")
        raw = json_value(json.loads(content))
        if not isinstance(raw, list):
            raise KctxError("malformed", "journal gate history must be an array")
        for row in raw:
            decode_gate_result(row)
        expected_gate_value = record["expected_gates"]
        expected_gates = (
            FileRevision(text(expected_gate_value, "expected_gates"))
            if expected_gate_value is not None
            else None
        )
        gate_path = gates_json_path(path)
        gate_revision = read_revision(gate_path)
        if gate_revision not in (expected_gates, revision_of(content)):
            raise KctxError(
                "conflict", f"{gate_path} changed during interrupted proposal publication"
            )
        if gate_revision != revision_of(content):
            compare_and_write(gate_path, content, expected=expected_gates)
    if current != revision_of(document):
        compare_and_write(path, document, expected=expected)
    journal.unlink()
    fsync_directory(journal.parent)


def publish(
    found: ProposalDocument, document: str, results: tuple[GateResult, ...] | None = None
) -> None:
    """Caller holds file_lock(found.path) and has admitted the entire candidate."""
    decode_proposal(parse_document(document))
    expected = revision_of(found.document.text.encode("utf-8"))
    if read_revision(found.path) != expected:
        raise KctxError("conflict", "proposal predecessor changed")
    if results is None:
        compare_and_write(found.path, document.encode("utf-8"), expected=expected)
        return
    encoded = [encode_gate_result(result) for result in results]
    for row in encoded:
        decode_gate_result(row)
    gate_path = gates_json_path(found.path)
    gate_revision = read_revision(gate_path)
    record = {
        "document": document,
        "expected_document": expected.val,
        "gates": json.dumps(encoded, indent=2) + "\n",
        "expected_gates": gate_revision.val if gate_revision is not None else None,
    }
    atomic_write_bytes(
        _journal_path(found.path), (json.dumps(record) + "\n").encode("utf-8"), exclusive=True
    )
    recover(found.path)
