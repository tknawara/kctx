"""Durable correction events, committed before lossless target updates."""

from __future__ import annotations

from pathlib import Path

from kctx.adapters.files.knowledge import canonical, digest
from kctx.adapters.files.knowledge import load as load_json
from kctx.adapters.files.mutations import (
    atomic_write_bytes,
    compare_and_write,
    file_lock,
    revision_of,
)
from kctx.adapters.files.storage import slugify
from kctx.codecs.documents import MarkdownDocument, parse_document, read_document, unfenced_lines
from kctx.domain.corrections import (
    Correction,
    CorrectionDocument,
    CorrectionOperation,
    CorrectionReferrer,
    CorrectionResult,
    CorrectionRow,
    CorrectionTarget,
    CorrectionTargetKind,
    UnchangedReview,
)
from kctx.domain.ids import AssetId, OperationId
from kctx.domain.json import JsonObject, JsonValue, object_value, text
from kctx.domain.targets import (
    AssetRef,
    DossierRef,
    EvidenceRef,
    ProposalRef,
    SigRef,
    parse_use_target,
)
from kctx.domain.time import today
from kctx.domain.vocabulary import CorrectionKind, CorrectionRowStatus
from kctx.errors import KctxError
from kctx.services import backlinks, dossiers, proposals, signatures


def corrections_root(root: Path) -> Path:
    return root / "corrections"


def all_paths(root: Path) -> tuple[Path, ...]:
    return tuple(sorted(corrections_root(root).glob("*.md")))


def parse_correction_target(raw: str) -> CorrectionTarget:
    target = parse_use_target(raw)
    if isinstance(target, (EvidenceRef, DossierRef, SigRef, ProposalRef)):
        return target
    if isinstance(target, AssetRef):
        return DossierRef(AssetId(target.ident))
    raise KctxError(
        "malformed",
        "retract doesn't support this target (no Corrections/Decision-log slot) -- ev:, a dossier asset id, sig:, and proposal/ only",
    )


def target_kind(target: CorrectionTarget) -> CorrectionTargetKind:
    if isinstance(target, EvidenceRef):
        return CorrectionTargetKind.EVIDENCE
    if isinstance(target, SigRef):
        return CorrectionTargetKind.SIGNATURE
    if isinstance(target, ProposalRef):
        return CorrectionTargetKind.PROPOSAL
    return CorrectionTargetKind.DOSSIER


def format_entry(
    *, date: str, kind: CorrectionKind, reason: str, by_replacement: str | None = None
) -> str:
    line = f"- {date}: {kind.value} — {reason}"
    if by_replacement:
        line += f" (replacement: {by_replacement})"
    return line


def render(record: Correction, referrers: tuple[CorrectionReferrer, ...]) -> str:
    lines = [
        "---",
        f"target: {record.target.spelling}",
        f"target_kind: {record.target_kind.value}",
        f"kind: {record.kind.value}",
        f"reason: {record.reason}",
        f"by_replacement: {record.by_replacement or ''}",
        f"created: {record.created}",
        "---",
        "",
        f"# Corrections: {record.target.spelling}",
        "",
    ]
    if not referrers:
        lines.extend(["(no known referrers at time of retraction)", ""])
        return "\n".join(lines)
    lines.extend(["| file | kind | status | owner |", "|---|---|---|---|"])
    lines.extend(f"| {r.file} | {r.kind} | pending | |" for r in referrers)
    lines.append("")
    return "\n".join(lines)


def parse_draft(text: str) -> MarkdownDocument:
    return parse_document(text)


def parse(text: str) -> CorrectionDocument:
    doc = parse_draft(text)
    fm = doc.frontmatter
    try:
        record = Correction(
            parse_correction_target(fm["target"]),
            CorrectionTargetKind(fm["target_kind"]),
            CorrectionKind(fm["kind"]),
            fm.get("reason", ""),
            fm.get("by_replacement") or None,
            fm.get("created", ""),
        )
    except (KeyError, ValueError) as exc:
        raise KctxError("malformed", f"invalid correction metadata: {exc}") from exc
    if record.target_kind is not target_kind(record.target):
        raise KctxError("malformed", "correction target_kind does not match target")
    rows: list[CorrectionRow] = []
    in_table = False
    for line in doc.unfenced_lines():
        stripped = line.strip()
        if not in_table:
            if stripped.startswith("| file "):
                in_table = True
            continue
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if all(set(c) <= {"-"} for c in cells):
            continue
        if len(cells) >= 4:
            raw_status = cells[2]
            status: CorrectionRowStatus | UnchangedReview
            if raw_status.startswith("unchanged:") and raw_status[len("unchanged:") :]:
                status = UnchangedReview(raw_status[len("unchanged:") :])
            else:
                try:
                    status = CorrectionRowStatus(raw_status)
                except ValueError as exc:
                    raise KctxError("malformed", f"bad row status {raw_status!r}") from exc
            rows.append(CorrectionRow(cells[0], cells[1], status, cells[3]))
    return CorrectionDocument(record, tuple(rows), doc)


def target_resolves(root: Path, target: CorrectionTarget) -> bool:
    try:
        if isinstance(target, EvidenceRef):
            return backlinks.resolve_ev_path(root, target.home, target.stem) is not None
        if isinstance(target, SigRef):
            return signatures.path_for_id(root, target.id).is_file()
        if isinstance(target, ProposalRef):
            proposals.load(root, target.id)
            return True
        return dossiers.dossier_path(root, target.id).is_file()
    except KctxError:
        return False


def _append_target_correction(
    root: Path, target: CorrectionTarget, entry_line: str, date: str
) -> Path:
    if isinstance(target, EvidenceRef):
        path = backlinks.resolve_ev_path(root, target.home, target.stem)
        if path is None:
            raise KctxError("not-found", f"no evidence record resolves for {target.spelling!r}")
        doc = read_document(path)
        heading = "Corrections"
    elif isinstance(target, SigRef):
        found_signature = signatures.load(root, target.id)
        path, doc, heading = (
            found_signature.path,
            found_signature.document,
            signatures.OPTIONAL_SECTION,
        )
    elif isinstance(target, ProposalRef):
        found_proposal = proposals.load(root, target.id)
        path, doc, heading = found_proposal.path, found_proposal.document, "Decision log"
    else:
        found_dossier = dossiers.load(root, target.id)
        path, doc, heading = (
            found_dossier.path,
            found_dossier.document,
            dossiers.CORRECTIONS_HEADING,
        )
    with file_lock(path):
        doc = read_document(path)
        expected = revision_of(doc.text.encode("utf-8"))
        existing = doc.sections.get(heading, "")
        if any(line.strip() == entry_line for _, line in unfenced_lines(existing)):
            return path
        if isinstance(target, (ProposalRef, DossierRef)):
            doc = doc.update_fields({"updated": date})
        if isinstance(target, EvidenceRef) and existing.strip().lower() == "none":
            doc = doc.update_section(heading, entry_line)
        else:
            doc = doc.append_section(heading, entry_line)
        compare_and_write(path, doc.text.encode("utf-8"), expected=expected)
    return path


def _unique_path(path: Path, reserved: frozenset[Path]) -> Path:
    if not path.exists() and path not in reserved:
        return path
    index = 2
    while True:
        candidate = path.with_name(f"{path.stem}-{index}{path.suffix}")
        if not candidate.exists() and candidate not in reserved:
            return candidate
        index += 1


def _input(
    target: CorrectionTarget, kind: CorrectionKind, reason: str, replacement: str | None
) -> JsonObject:
    return {
        "target": target.spelling,
        "kind": kind.value,
        "reason": reason,
        "by_replacement": replacement,
    }


def _encode_operation(operation: CorrectionOperation) -> JsonObject:
    record = operation.record
    refs: list[JsonValue] = [
        {"file": ref.file, "kind": ref.kind, "self": ref.self} for ref in operation.referrers
    ]
    return {
        "schema_version": 1,
        "id": operation.id.val,
        "input": _input(record.target, record.kind, record.reason, record.by_replacement),
        "created": record.created,
        "corrections_file": operation.corrections_file,
        "referrers": refs,
    }


def _decode_operation(raw: JsonObject) -> CorrectionOperation:
    if (
        set(raw) != {"schema_version", "id", "input", "created", "corrections_file", "referrers"}
        or type(raw["schema_version"]) is not int
        or raw["schema_version"] != 1
    ):
        raise KctxError("malformed", "invalid correction operation schema")
    request = object_value(raw["input"])
    if set(request) != {"target", "kind", "reason", "by_replacement"}:
        raise KctxError("malformed", "invalid correction operation input")
    target = parse_correction_target(text(request["target"], "target"))
    try:
        kind = CorrectionKind(text(request["kind"], "kind"))
    except ValueError as exc:
        raise KctxError("malformed", "invalid correction kind") from exc
    replacement = request["by_replacement"]
    if replacement is not None and not isinstance(replacement, str):
        raise KctxError("malformed", "invalid correction replacement")
    record = Correction(
        target,
        target_kind(target),
        kind,
        text(request["reason"], "reason"),
        replacement,
        text(raw["created"], "created"),
    )
    if (
        not record.reason.strip()
        or not record.created
        or any(
            "\n" in value or "\r" in value
            for value in (record.reason, record.by_replacement or "", record.created)
        )
    ):
        raise KctxError("malformed", "invalid correction event metadata")
    destination = text(raw["corrections_file"], "corrections_file")
    relative = Path(destination)
    if (
        relative.is_absolute()
        or len(relative.parts) != 2
        or relative.parts[:1] != ("corrections",)
        or ".." in relative.parts
        or relative.suffix != ".md"
    ):
        raise KctxError("malformed", "invalid correction projection path")
    raw_refs = raw["referrers"]
    if not isinstance(raw_refs, list):
        raise KctxError("malformed", "invalid correction referrers")
    refs: list[CorrectionReferrer] = []
    for value in raw_refs:
        ref = object_value(value)
        if set(ref) != {"file", "kind", "self"} or (
            ref["self"] is not None and type(ref["self"]) is not bool
        ):
            raise KctxError("malformed", "invalid correction referrer")
        own = ref["self"]
        refs.append(
            CorrectionReferrer(
                text(ref["file"], "file"),
                text(ref["kind"], "kind"),
                own if isinstance(own, bool) else None,
            )
        )
    return CorrectionOperation(OperationId(text(raw["id"], "id")), record, destination, tuple(refs))


def _project_tasks(root: Path, operation: CorrectionOperation) -> None:
    path = root / operation.corrections_file
    with file_lock(path):
        if not path.exists():
            compare_and_write(
                path, render(operation.record, operation.referrers).encode("utf-8"), expected=None
            )
            return
        doc = read_document(path)
        parsed = parse(doc.text)
        if parsed.frontmatter != operation.record:
            raise KctxError("conflict", "correction projection metadata differs from durable event")
        existing = {(row.file, row.kind) for row in parsed.rows}
        missing = tuple(ref for ref in operation.referrers if (ref.file, ref.kind) not in existing)
        if not missing:
            return
        # Keep authored review outcomes and owners; restore only missing task rows.
        insertion: int | None = None
        in_table = False
        for offset, line in unfenced_lines(doc.text):
            if line.strip().startswith("| file "):
                in_table = True
            elif in_table and not line.strip().startswith("|"):
                break
            if in_table:
                insertion = offset + len(line)
        rows = "".join(f"| {ref.file} | {ref.kind} | pending | |{doc.newline}" for ref in missing)
        if insertion is None:
            addition = (
                doc.newline
                + "| file | kind | status | owner |"
                + doc.newline
                + "|---|---|---|---|"
                + doc.newline
                + rows
            )
            updated = doc.text + addition
        else:
            prefix = "" if doc.text[:insertion].endswith(("\n", "\r")) else doc.newline
            updated = doc.text[:insertion] + prefix + rows + doc.text[insertion:]
        compare_and_write(
            path, updated.encode("utf-8"), expected=revision_of(doc.text.encode("utf-8"))
        )


def _replay(root: Path, operation: CorrectionOperation) -> CorrectionResult:
    _project_tasks(root, operation)
    record = operation.record
    entry = format_entry(
        date=record.created,
        kind=record.kind,
        reason=record.reason,
        by_replacement=record.by_replacement,
    )
    target_path = _append_target_correction(root, record.target, entry, record.created)
    return CorrectionResult(
        record.target,
        record.target_kind,
        str(target_path.relative_to(root)),
        record.kind,
        operation.corrections_file,
        operation.referrers,
    )


def recover(root: Path) -> tuple[CorrectionResult, ...]:
    """Replay durable events, repairing missing projections without new discovery."""
    with file_lock(corrections_root(root) / "journal"):
        operations = tuple(
            _decode_operation(load_json(path))
            for path in sorted((corrections_root(root) / ".events").glob("*.json"))
        )
        return tuple(_replay(root, operation) for operation in operations)


def retract(
    root: Path,
    target: CorrectionTarget,
    *,
    reason: str,
    kind: CorrectionKind,
    by_replacement: str | None = None,
    operation_id: OperationId | None = None,
) -> CorrectionResult:
    if not reason.strip():
        raise KctxError("incomplete", "retract requires --reason")
    if any("\n" in value or "\r" in value for value in (reason, by_replacement or "")):
        raise KctxError("malformed", "correction metadata must occupy one line")
    request = _input(target, kind, reason, by_replacement)
    identity = operation_id or OperationId(digest(canonical(request)))
    with file_lock(corrections_root(root) / "journal"):
        journal = (
            corrections_root(root) / ".events" / f"{digest(identity.val.encode('utf-8'))}.json"
        )
        if journal.exists():
            operation = _decode_operation(load_json(journal))
            record = operation.record
            if (
                operation.id != identity
                or _input(record.target, record.kind, record.reason, record.by_replacement)
                != request
            ):
                raise KctxError(
                    "conflict", "correction operation identity reused for different input"
                )
            return _replay(root, operation)
        created = today()
        record = Correction(target, target_kind(target), kind, reason, by_replacement, created)
        uses_result = backlinks.uses(root, target)
        referrers = tuple(
            CorrectionReferrer(r["file"], r["kind"], r.get("self"))
            for r in uses_result["referrers"]
            if not r.get("self")
        )
        reserved = frozenset(
            root / _decode_operation(load_json(event)).corrections_file
            for event in journal.parent.glob("*.json")
        )
        path = _unique_path(
            corrections_root(root) / f"{created}-{slugify(target.spelling)}.md", reserved
        )
        operation = CorrectionOperation(identity, record, str(path.relative_to(root)), referrers)
        # The canonical event is durable before either independently replayable
        # task/target projection. No cross-file atomicity is claimed.
        atomic_write_bytes(journal, canonical(_encode_operation(operation)), exclusive=True)
        return _replay(root, operation)


def frontmatter_to_wire(record: Correction) -> dict[str, object]:
    return {
        "target": record.target.spelling,
        "target_kind": record.target_kind.value,
        "kind": record.kind.value,
        "reason": record.reason,
        "by_replacement": record.by_replacement or "",
        "created": record.created,
    }


def result_to_wire(result: CorrectionResult) -> dict[str, object]:
    referrers: list[dict[str, object]] = []
    for referrer in result.referrers:
        row: dict[str, object] = {"file": referrer.file, "kind": referrer.kind}
        if referrer.self is not None:
            row["self"] = referrer.self
        referrers.append(row)
    return {
        "target": result.target.spelling,
        "target_kind": result.target_kind.value,
        "target_file": result.target_file,
        "kind": result.kind.value,
        "corrections_file": result.corrections_file,
        "referrers": referrers,
    }
