"""Ticket work records, normalized once at the command boundary."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from kctx.adapters.files.mutations import compare_and_write, file_lock, revision_of
from kctx.adapters.files.storage import slugify
from kctx.codecs.documents import MarkdownDocument, parse_document, read_document, render_document
from kctx.codecs.frontmatter import split_list_value
from kctx.domain.ids import AssetId, TicketId
from kctx.domain.incidents import Ktlo, KtloCreated, KtloPromoted, LoadedDocument, ParsedDocument
from kctx.domain.time import today
from kctx.domain.vocabulary import KtloStatus
from kctx.errors import KctxError
from kctx.services.investigations import append_log_pointer

SECTION_ORDER = ["Symptom", "Evidence", "Change", "Outcome"]
TICKET_RE = re.compile(r"^\{?\s*([A-Za-z]+)[\s-]*(\d+)\s*\}?$")


def normalize_ticket(raw: str) -> TicketId:
    match = TICKET_RE.match(raw.strip())
    if not match:
        raise KctxError("malformed", f"unrecognized ticket id {raw!r}")
    return TicketId(f"{match.group(1).upper()}-{match.group(2)}")


def ktlo_root(root: Path) -> Path:
    return root / "ktlo"


def parse_draft(text: str) -> MarkdownDocument:
    return parse_document(text)


def _decode(doc: MarkdownDocument) -> Ktlo:
    fm = doc.frontmatter
    try:
        return Ktlo(
            TicketId(fm["ticket"]),
            fm.get("title", ""),
            tuple(AssetId(v) for v in split_list_value(fm.get("assets", ""))),
            KtloStatus(fm["status"]),
            tuple(split_list_value(fm.get("prs", ""))),
            fm.get("summary", ""),
            fm.get("created", ""),
            fm.get("updated", ""),
            fm.get("promoted_to") or None,
        )
    except (KeyError, ValueError) as exc:
        raise KctxError("malformed", f"invalid ktlo metadata: {exc}") from exc


def parse(text: str) -> ParsedDocument[Ktlo]:
    doc = parse_draft(text)
    return ParsedDocument(_decode(doc), doc)


def frontmatter_to_wire(record: Ktlo) -> dict[str, object]:
    return {
        "ticket": record.ticket.val,
        "title": record.title,
        "assets": [v.val for v in record.assets],
        "status": record.status.value,
        "prs": list(record.prs),
        "summary": record.summary,
        "created": record.created,
        "updated": record.updated,
        "promoted_to": record.promoted_to,
    }


def render(record: Ktlo, body: Mapping[str, str]) -> str:
    fields = {
        "ticket": record.ticket.val,
        "title": record.title,
        "assets": "[" + ", ".join(v.val for v in record.assets) + "]",
        "status": record.status.value,
        "prs": "[" + ", ".join(record.prs) + "]",
        "summary": record.summary,
        "created": record.created,
        "updated": record.updated,
        "promoted_to": record.promoted_to,
    }
    return render_document(
        fields,
        {s: body.get(s, "") for s in SECTION_ORDER},
        title=f"{record.ticket.val}: {record.title}",
    ).text


def all_paths(root: Path) -> tuple[Path, ...]:
    return tuple(sorted(ktlo_root(root).glob("*/*.md")))


def new(
    root: Path, *, ticket: TicketId, title: str, assets: tuple[AssetId, ...] = ()
) -> KtloCreated:
    created = today()
    path = ktlo_root(root) / created[:4] / f"{ticket.val.lower()}-{slugify(title)}.md"
    if path.exists():
        raise KctxError("conflict", f"ktlo record {path} already exists")
    record = Ktlo(ticket, title, assets, KtloStatus.TODO, (), "", created, created, None)
    text = render(record, {})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return KtloCreated(ticket, path, record)


def load_by_ticket(root: Path, ticket: TicketId) -> LoadedDocument[Ktlo]:
    for path in all_paths(root):
        doc = read_document(path)
        record = _decode(doc)
        if record.ticket == ticket:
            return LoadedDocument(path, record, doc)
    raise KctxError("not-found", f"ktlo record for ticket {ticket} not found")


def promote(root: Path, ticket: TicketId, project: str) -> KtloPromoted:
    path = load_by_ticket(root, ticket).path
    with file_lock(path):
        doc = read_document(path)
        record = _decode(doc)
        already = record.promoted_to == project
        if not already:
            updated = doc.update_fields({"promoted_to": project, "updated": today()})
            compare_and_write(
                path, updated.text.encode("utf-8"), expected=revision_of(doc.text.encode("utf-8"))
            )
        rel = path.relative_to(ktlo_root(root)).as_posix()
        append_log_pointer(root, project, f"ktlo promote: {ticket} -> {project} (ktlo/{rel})")
        return KtloPromoted(ticket, project, path, already)


def result_to_wire(result: KtloCreated | KtloPromoted) -> dict[str, object]:
    if isinstance(result, KtloCreated):
        return {
            "ticket": result.ticket.val,
            "path": str(result.path),
            "frontmatter": frontmatter_to_wire(result.frontmatter),
        }
    return {
        "ticket": result.ticket.val,
        "project": result.project,
        "path": str(result.path),
        "already_promoted": result.already_promoted,
    }
