"""Incident investigations, with typed metadata and lossless authored updates."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from kctx.adapters.files.mutations import compare_and_write, file_lock, revision_of
from kctx.adapters.files.storage import slugify
from kctx.codecs.documents import (
    MarkdownDocument,
    parse_document,
    read_document,
    render_document,
    unfenced_lines,
)
from kctx.codecs.frontmatter import split_list_value
from kctx.domain.ids import AssetId, InvestigationId, SignatureId, TicketId
from kctx.domain.incidents import (
    FollowUp,
    FollowUpStatus,
    Hypothesis,
    Investigation,
    InvestigationCreated,
    InvestigationPromoted,
    InvestigationShown,
    LoadedDocument,
    ParsedDocument,
    ProjectRef,
)
from kctx.domain.time import today
from kctx.domain.vocabulary import HypothesisStatus, InvestigationStatus, InvestigationTrigger
from kctx.errors import KctxError
from kctx.semantics import model as semantic_model
from kctx.semantics import workflow as semantic_workflow

SECTION_ORDER = [
    "Trigger and symptom",
    "Impact",
    "Timeline",
    "Recurrence check",
    "Hypotheses",
    "Findings",
    "Scope and limits",
    "Follow-ups",
    "Learned",
    "What made it hard / what went well",
    "Checked against",
]
_HYPOTHESIS_RE = re.compile(r"^[-*]\s*(H\d+)\s*:\s*(open|supported|refuted|unk)\b", re.IGNORECASE)
_HYPOTHESIS_CANDIDATE_RE = re.compile(r"^[-*]\s*H\d+\b", re.IGNORECASE)
_TICKET_RE = re.compile(r"^[A-Z]+-\d+$")


def investigations_root(root: Path) -> Path:
    return root / "investigations"


def path_for_id(root: Path, inv_id: InvestigationId) -> Path:
    return investigations_root(root) / inv_id.val / "README.md"


def parse_draft(text: str) -> MarkdownDocument:
    return parse_document(text)


def _parse_follow_up(raw: str) -> FollowUp:
    parts = raw.split(":")
    if len(parts) > 3:
        raise KctxError("malformed", f"invalid follow-up {raw!r}")
    owner = parts[0].strip()
    status = parts[1].strip() if len(parts) > 1 else ""
    ticket = parts[2].strip() if len(parts) > 2 else ""
    return FollowUp(owner, FollowUpStatus(status), TicketId(ticket) if ticket else None)


def _decode(doc: MarkdownDocument) -> Investigation:
    fm = doc.frontmatter
    try:
        return Investigation(
            InvestigationId(fm["id"]),
            fm.get("title", ""),
            InvestigationTrigger(fm["trigger"]),
            tuple(TicketId(v) for v in split_list_value(fm.get("tickets", ""))),
            tuple(AssetId(v) for v in split_list_value(fm.get("alerts", ""))),
            tuple(AssetId(v) for v in split_list_value(fm.get("assets", ""))),
            tuple(split_list_value(fm.get("windows", ""))),
            fm.get("impact_summary", ""),
            InvestigationStatus(fm["status"]),
            tuple(SignatureId(v) for v in split_list_value(fm.get("signatures", ""))),
            tuple(_parse_follow_up(v) for v in split_list_value(fm.get("follow_ups", ""))),
            tuple(
                TicketId(v) if _TICKET_RE.fullmatch(v) else ProjectRef(v)
                for v in split_list_value(fm.get("spawned", ""))
            ),
            fm.get("promoted_to") or None,
            fm.get("created", ""),
            fm.get("updated", ""),
            fm.get("summary", ""),
        )
    except (KeyError, ValueError) as exc:
        raise KctxError("malformed", f"invalid investigation metadata: {exc}") from exc


def parse(text: str) -> ParsedDocument[Investigation]:
    doc = parse_draft(text)
    return ParsedDocument(_decode(doc), doc)


def frontmatter_to_wire(record: Investigation) -> dict[str, object]:
    return {
        "id": record.id.val,
        "title": record.title,
        "trigger": record.trigger.value,
        "tickets": [v.val for v in record.tickets],
        "alerts": [v.val for v in record.alerts],
        "assets": [v.val for v in record.assets],
        "windows": list(record.windows),
        "impact_summary": record.impact_summary,
        "status": record.status.value,
        "signatures": [v.val for v in record.signatures],
        "follow_ups": [
            {"owner": v.owner, "status": v.status.text, "ticket": v.ticket.val if v.ticket else ""}
            for v in record.follow_ups
        ],
        "spawned": [v.val if isinstance(v, TicketId) else v.name for v in record.spawned],
        "promoted_to": record.promoted_to,
        "created": record.created,
        "updated": record.updated,
        "summary": record.summary,
    }


def render(record: Investigation, body: Mapping[str, str]) -> str:
    fields = {
        "id": record.id.val,
        "title": record.title,
        "trigger": record.trigger.value,
        "tickets": "[" + ", ".join(v.val for v in record.tickets) + "]",
        "alerts": "[" + ", ".join(v.val for v in record.alerts) + "]",
        "assets": "[" + ", ".join(v.val for v in record.assets) + "]",
        "windows": "[" + ", ".join(record.windows) + "]",
        "impact_summary": record.impact_summary,
        "status": record.status.value,
        "signatures": "[" + ", ".join(v.val for v in record.signatures) + "]",
        "follow_ups": "["
        + ", ".join(
            v.owner + ":" + v.status.text + (":" + v.ticket.val if v.ticket else "")
            for v in record.follow_ups
        )
        + "]",
        "spawned": "["
        + ", ".join(v.val if isinstance(v, TicketId) else v.name for v in record.spawned)
        + "]",
        "promoted_to": record.promoted_to,
        "created": record.created,
        "updated": record.updated,
        "summary": record.summary,
    }
    return render_document(
        fields, {s: body.get(s, "") for s in SECTION_ORDER}, title=record.title
    ).text


def all_paths(root: Path) -> tuple[Path, ...]:
    return tuple(sorted(investigations_root(root).glob("*/*/README.md")))


def new(
    root: Path,
    slug: str,
    *,
    trigger: InvestigationTrigger,
    title: str | None = None,
    tickets: tuple[TicketId, ...] = (),
    alerts: tuple[AssetId, ...] = (),
    assets: tuple[AssetId, ...] = (),
    windows: tuple[str, ...] = (),
    impact_summary: str = "",
    created: str | None = None,
) -> InvestigationCreated:
    created = created or today()
    inv_id = InvestigationId(f"{created[:4]}/{created}-{slugify(slug)}")
    path = path_for_id(root, inv_id)
    if path.exists():
        raise KctxError("conflict", f"investigation {inv_id} already exists")
    record = Investigation(
        inv_id,
        title or slug.replace("-", " "),
        trigger,
        tickets,
        alerts,
        assets,
        windows,
        impact_summary,
        InvestigationStatus.OPEN,
        (),
        (),
        (),
        None,
        created,
        created,
        "",
    )
    text = render(record, {})
    path.parent.mkdir(parents=True, exist_ok=True)
    (path.parent / "evidence").mkdir(exist_ok=True)
    (path.parent / "queries").mkdir(exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return InvestigationCreated(inv_id, path, record)


def load(root: Path, inv_id: InvestigationId) -> LoadedDocument[Investigation]:
    path = path_for_id(root, inv_id)
    if not path.exists():
        raise KctxError("not-found", f"investigation {inv_id} not found")
    doc = read_document(path)
    return LoadedDocument(path, _decode(doc), doc)


def list_investigations(
    root: Path, *, open_only: bool = False, asset: AssetId | None = None
) -> tuple[Investigation, ...]:
    out: list[Investigation] = []
    for path in all_paths(root):
        record = _decode(read_document(path))
        if open_only and record.status not in (
            InvestigationStatus.OPEN,
            InvestigationStatus.MONITORING,
        ):
            continue
        if asset and asset not in record.assets and asset not in record.alerts:
            continue
        out.append(record)
    return tuple(out)


def show(root: Path, inv_id: InvestigationId) -> InvestigationShown:
    found = load(root, inv_id)
    home = found.path.parent
    return InvestigationShown(
        found.frontmatter.id,
        found.frontmatter,
        tuple(s for s in SECTION_ORDER if s in found.body),
        tuple(sorted(p.name for p in (home / "evidence").glob("*.md"))),
        tuple(sorted(p.name for p in (home / "queries").glob("*"))),
    )


def parse_hypotheses(text: str) -> tuple[Hypothesis, ...]:
    out: list[Hypothesis] = []
    for _, line in unfenced_lines(text):
        stripped = line.strip()
        match = _HYPOTHESIS_RE.match(stripped)
        if match:
            out.append(
                Hypothesis(match.group(1), HypothesisStatus(match.group(2).lower()), stripped)
            )
        elif _HYPOTHESIS_CANDIDATE_RE.match(stripped):
            raise KctxError("malformed", f"invalid hypothesis bullet: {stripped!r}")
    return tuple(out)


def conclusion_problems(body: Mapping[str, str]) -> tuple[str, ...]:
    """Assess authored completion using the same predicate as the mutation.

    Malformed hypothesis bullets raise ``KctxError``; legitimate open drafts
    return readiness diagnostics. Empty/unknown hypotheses remain structural
    completion, not admission of factual claims.
    """
    hypotheses = parse_hypotheses(body.get("Hypotheses", ""))
    outcomes = {
        HypothesisStatus.SUPPORTED: semantic_model.HypothesisStatus.SUPPORTED,
        HypothesisStatus.REFUTED: semantic_model.HypothesisStatus.REFUTED,
        HypothesisStatus.UNK: semantic_model.HypothesisStatus.UNKNOWN,
        HypothesisStatus.OPEN: semantic_model.HypothesisStatus.OPEN,
    }
    summary = semantic_model.Investigation(
        body.get("Checked against", ""),
        body.get("Scope and limits", ""),
        tuple(semantic_model.Hypothesis(h.text, outcomes[h.status]) for h in hypotheses),
    )
    if semantic_workflow.conclude(summary):
        return ()
    missing = [
        section
        for section in ("Checked against", "Scope and limits")
        if not body.get(section, "").strip()
    ]
    open_hyps = [h.id for h in hypotheses if h.status is HypothesisStatus.OPEN]
    if open_hyps:
        missing.append(f"Hypotheses still open: {', '.join(open_hyps)}")
    return tuple(missing) or ("structural conclusion rejected",)


def conclude(root: Path, inv_id: InvestigationId) -> Investigation:
    with file_lock(path_for_id(root, inv_id)):
        found = load(root, inv_id)
        missing = conclusion_problems(found.body)
        if missing:
            raise KctxError("incomplete", f"cannot conclude {inv_id}: missing {'; '.join(missing)}")
        record = replace(found.frontmatter, status=InvestigationStatus.CONCLUDED, updated=today())
        updated = found.document.update_fields(
            {"status": record.status.value, "updated": record.updated}
        )
        compare_and_write(
            found.path,
            updated.text.encode("utf-8"),
            expected=revision_of(found.document.text.encode("utf-8")),
        )
        return record


LOG_TEMPLATE = (
    "---\nsummary:\ntags: []\n---\n# {date}\n\n## Done\n-\n\n## Findings\n-\n\n## Next\n-\n"
)


def append_log_pointer(root: Path, project: str, pointer: str) -> None:
    log_dir = root / project / "log"
    with file_lock(log_dir / "promotions"):
        # A delayed retry belongs to the original promotion, not a new day's event.
        for existing_path in sorted(log_dir.glob("*.md")):
            existing_text = existing_path.read_bytes().decode("utf-8")
            if any(line.strip() == f"- {pointer}" for _, line in unfenced_lines(existing_text)):
                return
        path = log_dir / f"{today()}.md"
        with file_lock(path):
            exists = path.exists()
            doc = (
                read_document(path) if exists else parse_document(LOG_TEMPLATE.format(date=today()))
            )
            existing = doc.sections.get("Done", "")
            updated = doc.update_section("Done", f"- {pointer}\n{existing}".rstrip())
            compare_and_write(
                path,
                updated.text.encode("utf-8"),
                expected=revision_of(doc.text.encode("utf-8")) if exists else None,
            )


def promote(root: Path, inv_id: InvestigationId, project: str) -> InvestigationPromoted:
    with file_lock(path_for_id(root, inv_id)):
        found = load(root, inv_id)
        already = found.frontmatter.promoted_to == project
        if not already:
            updated = found.document.update_fields({"promoted_to": project, "updated": today()})
            compare_and_write(
                found.path,
                updated.text.encode("utf-8"),
                expected=revision_of(found.document.text.encode("utf-8")),
            )
        pointer = (
            f"investigation promote: {inv_id} -> {project} (investigations/{inv_id}/README.md)"
        )
        append_log_pointer(root, project, pointer)
        return InvestigationPromoted(inv_id, project, found.path, already)


def result_to_wire(
    result: InvestigationCreated | InvestigationShown | InvestigationPromoted | Investigation,
) -> dict[str, object]:
    if isinstance(result, Investigation):
        return frontmatter_to_wire(result)
    if isinstance(result, InvestigationPromoted):
        return {
            "id": result.id.val,
            "project": result.project,
            "path": str(result.path),
            "already_promoted": result.already_promoted,
        }
    out: dict[str, object] = {
        "id": result.id.val,
        "frontmatter": frontmatter_to_wire(result.frontmatter),
    }
    if isinstance(result, InvestigationCreated):
        out["path"] = str(result.path)
    else:
        out.update(
            sections=list(result.sections),
            evidence=list(result.evidence),
            queries=list(result.queries),
        )
    return out
