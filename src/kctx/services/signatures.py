"""Known-error signatures; authored edits use the shared lossless document codec."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from kctx.adapters.files.storage import slugify
from kctx.codecs.documents import MarkdownDocument, parse_document, read_document, render_document
from kctx.codecs.frontmatter import split_list_value
from kctx.domain.ids import AssetId, ProposalId, SignatureId
from kctx.domain.incidents import (
    LoadedDocument,
    ParsedDocument,
    Signature,
    SignatureCreated,
    SignatureMatch,
    SignatureShown,
)
from kctx.domain.vocabulary import SignatureStatus
from kctx.errors import KctxError

SECTION_ORDER = ["Signature", "Mechanism", "Workaround", "Fix and status", "Learned"]
OPTIONAL_SECTION = "Corrections"


def signatures_root(root: Path) -> Path:
    return root / "signatures"


def path_for_id(root: Path, sig_id: SignatureId) -> Path:
    return signatures_root(root) / f"{sig_id.val}.md"


def parse_draft(text: str) -> MarkdownDocument:
    return parse_document(text)


def _decode(doc: MarkdownDocument) -> Signature:
    fm = doc.frontmatter
    try:
        return Signature(
            SignatureId(fm["id"]),
            fm.get("title", ""),
            SignatureStatus(fm["status"]),
            tuple(split_list_value(fm.get("match", ""))),
            fm.get("match_where", ""),
            tuple(AssetId(v) for v in split_list_value(fm.get("assets", ""))),
            fm.get("owner_group") or None,
            fm.get("first_seen") or None,
            fm.get("last_seen") or None,
            fm.get("workaround", ""),
            tuple(ProposalId(v) for v in split_list_value(fm.get("fix", ""))),
            fm.get("fixed_at") or None,
            fm.get("verified_at") or None,
            fm.get("ttl") or None,
        )
    except (KeyError, ValueError) as exc:
        raise KctxError("malformed", f"invalid signature metadata: {exc}") from exc


def parse(text: str) -> ParsedDocument[Signature]:
    doc = parse_draft(text)
    return ParsedDocument(_decode(doc), doc)


def frontmatter_to_wire(record: Signature) -> dict[str, object]:
    return {
        "id": record.id.val,
        "title": record.title,
        "status": record.status.value,
        "match": list(record.match),
        "match_where": record.match_where,
        "assets": [v.val for v in record.assets],
        "owner_group": record.owner_group,
        "first_seen": record.first_seen,
        "last_seen": record.last_seen,
        "workaround": record.workaround,
        "fix": [v.val for v in record.fix],
        "fixed_at": record.fixed_at,
        "verified_at": record.verified_at,
        "ttl": record.ttl,
    }


def render(record: Signature, body: Mapping[str, str]) -> str:
    fields = {
        "id": record.id.val,
        "title": record.title,
        "status": record.status.value,
        "match": "[" + ", ".join(record.match) + "]",
        "match_where": record.match_where,
        "assets": "[" + ", ".join(v.val for v in record.assets) + "]",
        "owner_group": record.owner_group,
        "first_seen": record.first_seen,
        "last_seen": record.last_seen,
        "workaround": record.workaround,
        "fix": "[" + ", ".join(v.val for v in record.fix) + "]",
        "fixed_at": record.fixed_at,
        "verified_at": record.verified_at,
        "ttl": record.ttl,
    }
    sections = {s: body.get(s, "") for s in SECTION_ORDER}
    if OPTIONAL_SECTION in body:
        sections[OPTIONAL_SECTION] = body[OPTIONAL_SECTION]
    return render_document(fields, sections, title=record.title).text


def all_paths(root: Path) -> tuple[Path, ...]:
    return tuple(sorted(signatures_root(root).glob("*.md")))


def new(
    root: Path,
    slug: str,
    *,
    title: str | None = None,
    match: tuple[str, ...] = (),
    match_where: str = "",
    assets: tuple[AssetId, ...] = (),
    owner_group: str | None = None,
    status: SignatureStatus = SignatureStatus.SUSPECTED,
    first_seen: str | None = None,
    last_seen: str | None = None,
    workaround: str = "",
    fix: tuple[ProposalId, ...] = (),
    fixed_at: str | None = None,
    verified_at: str | None = None,
    ttl: str | None = None,
) -> SignatureCreated:
    sig_id = SignatureId(slugify(slug))
    path = path_for_id(root, sig_id)
    if path.exists():
        raise KctxError("conflict", f"signature {sig_id} already exists")
    record = Signature(
        sig_id,
        title or slug.replace("-", " "),
        status,
        match,
        match_where,
        assets,
        owner_group,
        first_seen,
        last_seen,
        workaround,
        fix,
        fixed_at,
        verified_at,
        ttl,
    )
    text = render(record, {})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return SignatureCreated(sig_id, path, record)


def load(root: Path, sig_id: SignatureId) -> LoadedDocument[Signature]:
    path = path_for_id(root, sig_id)
    if not path.exists():
        raise KctxError("not-found", f"signature {sig_id} not found")
    doc = read_document(path)
    return LoadedDocument(path, _decode(doc), doc)


def list_signatures(root: Path, *, skipped: list[str] | None = None) -> tuple[Signature, ...]:
    """Decode every signature; aggregate readers pass ``skipped`` so one
    malformed record limits its own reporting, not the whole command."""
    out: list[Signature] = []
    for path in all_paths(root):
        try:
            out.append(_decode(read_document(path)))
        except (KctxError, ValueError, OSError) as error:
            if skipped is None:
                raise
            skipped.append(f"signature {path.relative_to(root)}: {error}")
    return tuple(out)


def show(root: Path, sig_id: SignatureId) -> SignatureShown:
    found = load(root, sig_id)
    return SignatureShown(
        found.frontmatter.id,
        found.frontmatter,
        tuple(s for s in [*SECTION_ORDER, OPTIONAL_SECTION] if s in found.body),
    )


def _pattern_matches(pattern: str, text: str) -> bool:
    if pattern.startswith("re:"):
        try:
            return re.search(pattern[3:], text, re.IGNORECASE) is not None
        except re.error:
            return False
    return pattern.lower() in text.lower()


def match_signatures(
    root: Path, text: str, *, skipped: list[str] | None = None
) -> tuple[SignatureMatch, ...]:
    hits: list[SignatureMatch] = []
    for record in list_signatures(root, skipped=skipped):
        matched = tuple(p for p in record.match if _pattern_matches(p, text))
        if matched:
            hits.append(
                SignatureMatch(
                    record.id,
                    record.title,
                    record.status,
                    record.workaround,
                    record.owner_group,
                    record.last_seen,
                    matched,
                )
            )
    hits.sort(key=lambda h: -len(h.matched_patterns))
    return tuple(hits)


def result_to_wire(result: SignatureCreated | SignatureShown | SignatureMatch) -> dict[str, object]:
    if isinstance(result, SignatureMatch):
        return {
            "id": result.id.val,
            "title": result.title,
            "status": result.status.value,
            "workaround": result.workaround,
            "owner_group": result.owner_group,
            "last_seen": result.last_seen,
            "matched_patterns": list(result.matched_patterns),
        }
    out: dict[str, object] = {
        "id": result.id.val,
        "frontmatter": frontmatter_to_wire(result.frontmatter),
    }
    if isinstance(result, SignatureCreated):
        out["path"] = str(result.path)
    else:
        out["sections"] = list(result.sections)
    return out
