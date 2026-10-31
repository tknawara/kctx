"""Acceptance-gate definitions and revision-bound append-only outcomes."""

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

from kctx.adapters.files.mutations import atomic_write_bytes, file_lock
from kctx.adapters.files.storage import read_json
from kctx.codecs.documents import unfenced_lines
from kctx.codecs.gates import decode_gate_result, encode_gate_result
from kctx.domain.ids import GateId
from kctx.domain.json import json_value
from kctx.domain.proposals import GateDefinition, GateResult
from kctx.domain.time import iso_now
from kctx.domain.vocabulary import GateOutcome, GateWhen
from kctx.errors import KctxError

_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")
_SEP_CELL_RE = re.compile(r"^:?-+:?$")
_GATES_HEADING_RE = re.compile(r"^#{1,6}\s*Acceptance gates\s*$", re.IGNORECASE)
_ANY_HEADING_RE = re.compile(r"^#{1,6}\s")


def _section_text(section: str | Mapping[str, str]) -> str:
    if isinstance(section, str):
        return section
    candidates: list[str] = []
    if "Acceptance gates" in section:
        candidates.append(section["Acceptance gates"])
    for text in section.values():
        start: int | None = None
        for offset, line in unfenced_lines(text):
            if start is not None and _ANY_HEADING_RE.match(line.strip()):
                candidates.append("\n".join(text[start:offset].splitlines()))
                start = None
            if _GATES_HEADING_RE.match(line.strip()):
                start = offset + len(line)
        if start is not None:
            candidates.append("\n".join(text[start:].splitlines()))
    if len(candidates) > 1:
        raise KctxError("malformed", "duplicate Acceptance gates sections")
    return candidates[0] if candidates else ""


def parse_gates_table(section: str | Mapping[str, str]) -> tuple[GateDefinition, ...]:
    """Admit a gate table; prose/absent tables remain legacy-empty.

    Incomplete columns are not runnable tables. Once id/when columns exist,
    malformed rows, duplicate identities and unknown timing are diagnosed.
    """
    rows: list[list[str]] = []
    for _, line in unfenced_lines(_section_text(section)):
        match = _ROW_RE.match(line)
        if match:
            rows.append([cell.strip() for cell in match[1].split("|")])
    if not rows:
        return ()
    header = [cell.lower() for cell in rows[0]]
    if "id" not in header or "when" not in header:
        raise KctxError("malformed", "Acceptance gates table requires id and when columns")
    if len(header) != len(set(header)):
        raise KctxError("malformed", "duplicate Acceptance gates table column")
    index = {name: i for i, name in enumerate(header)}
    gates: list[GateDefinition] = []
    seen: set[GateId] = set()
    for row in rows[1:]:
        if all(_SEP_CELL_RE.match(cell) for cell in row if cell):
            continue
        if len(row) != len(header):
            raise KctxError("malformed", "Acceptance gates table row has wrong number of cells")
        try:
            identity = GateId(row[index["id"]])
            when = GateWhen(row[index["when"]])
        except ValueError as exc:
            raise KctxError("malformed", f"invalid Acceptance gate: {exc}") from exc
        if identity in seen:
            raise KctxError("malformed", f"duplicate Acceptance gate {identity.val!r}")
        seen.add(identity)
        gates.append(
            GateDefinition(
                identity,
                when,
                row[index["claim"]] if "claim" in index else None,
                row[index["check"]] if "check" in index else None,
                row[index["by"]] if "by" in index else None,
                row[index["checker"]] if "checker" in index else None,
            )
        )
    return tuple(gates)


def gates_rev(section: str | Mapping[str, str]) -> str:
    """Keep historical digest semantics; unrelated document edits do not bind."""
    text = _section_text(section).replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def gates_json_path(proposal_md_path: Path) -> Path:
    if proposal_md_path.name == "proposal.md":
        return proposal_md_path.parent / "gates.json"
    return proposal_md_path.parent / f"{proposal_md_path.stem}.gates.json"


def load_results(proposal_md_path: Path) -> tuple[GateResult, ...]:
    path = gates_json_path(proposal_md_path)
    if not path.exists():
        return ()
    data = json_value(read_json(path), str(path))
    if not isinstance(data, list):
        raise KctxError("malformed", f"{path}: expected a JSON list")
    return tuple(decode_gate_result(entry) for entry in data)


def latest_outcomes(
    results: tuple[GateResult, ...], rev: str | None = None
) -> Mapping[GateId, GateOutcome]:
    latest: dict[GateId, GateOutcome] = {}
    for result in results:
        if rev is None or result.rev in (None, rev):
            latest[result.gate] = result.outcome
    return MappingProxyType(latest)


def append_result(
    proposal_md_path: Path,
    *,
    gate: GateId,
    outcome: GateOutcome,
    evidence: str,
    by: str | None = None,
    rev: str | None = None,
) -> GateResult:
    """Append a legacy unbound historical result; it cannot authorize transitions."""
    from kctx.services.proposal_mutation import recover

    with file_lock(proposal_md_path):
        recover(proposal_md_path)
        entry = GateResult(gate, outcome, evidence, iso_now(), by or None, rev or None)
        results = (*load_results(proposal_md_path), entry)
        content = json.dumps([encode_gate_result(result) for result in results], indent=2) + "\n"
        atomic_write_bytes(gates_json_path(proposal_md_path), content.encode("utf-8"))
        return entry


def pending_for_when(
    table: tuple[GateDefinition, ...],
    results: tuple[GateResult, ...],
    whens: frozenset[GateWhen],
    rev: str | None = None,
) -> tuple[GateId, ...]:
    latest = latest_outcomes(results, rev)
    return tuple(
        gate.id
        for gate in table
        if gate.when in whens and latest.get(gate.id) is not GateOutcome.PASS
    )
