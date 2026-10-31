"""Resolve authored records through the shared workspace and document codec."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from kctx.adapters.files.roots import find_root
from kctx.codecs.documents import MarkdownDocument, read_document
from kctx.config import Config
from kctx.domain.ids import ProposalId
from kctx.domain.targets import EvidenceRef, parse_use_target
from kctx.errors import KctxError


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    source: str
    excerpt: str


@dataclass(frozen=True, slots=True)
class ProposalRecord:
    status: str
    path: Path


def projects_root(*, config: Config | None = None) -> Path:
    if config is None or config.root is None:
        return find_root()
    if not config.root.is_dir():
        raise KctxError("not-found", f"knowledge workspace does not exist: {config.root}")
    return config.root.resolve()


def resolve_under_projects_root(rel: str, *, config: Config | None = None) -> Path:
    pure = PurePosixPath(rel)
    if (
        not rel
        or rel == "."
        or pure.is_absolute()
        or ".." in pure.parts
        or "\\" in rel
        or "\x00" in rel
    ):
        raise KctxError("malformed", f"{rel!r} is not a safe path relative to the projects root")
    root = projects_root(config=config)
    try:
        path = (root / rel).resolve()
    except (OSError, RuntimeError) as error:
        raise KctxError(
            "malformed", f"cannot resolve record path {rel!r}: {str(error)[:500]}"
        ) from error
    if not path.is_relative_to(root):
        raise KctxError("malformed", f"record path {rel!r} escapes the projects root")
    return path


def _load(path: Path) -> MarkdownDocument | None:
    try:
        return read_document(path)
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError) as error:
        raise KctxError("not-found", f"cannot read record {path}: {str(error)[:500]}") from error


def load_evidence_record(
    id_: EvidenceRef | str, *, config: Config | None = None
) -> EvidenceRecord | None:
    if isinstance(id_, str):
        reference = parse_use_target(id_ if id_.startswith("ev:") else f"ev:{id_}")
        if not isinstance(reference, EvidenceRef):
            raise KctxError("malformed", f"invalid evidence reference: {id_!r}")
    else:
        reference = id_
    path = resolve_under_projects_root(
        f"{reference.home}/evidence/{reference.stem.val}.md", config=config
    )
    document = _load(path)
    if document is None:
        return None
    return EvidenceRecord(document.frontmatter.get("source", "(none)"), document.body.strip())


def load_proposal_record(
    id_: ProposalId | str, *, config: Config | None = None
) -> ProposalRecord | None:
    identity = ProposalId(id_) if isinstance(id_, str) else id_
    for rel in (f"proposals/{identity.val}.md", f"proposals/{identity.val}/proposal.md"):
        path = resolve_under_projects_root(rel, config=config)
        document = _load(path)
        if document is not None:
            return ProposalRecord(document.frontmatter.get("status", ""), path)
    return None


def load_record_status(path_rel: str, *, config: Config | None = None) -> str | None:
    document = _load(resolve_under_projects_root(path_rel, config=config))
    if document is None:
        return None
    status = document.frontmatter.get("status")
    if not status:
        raise KctxError("malformed", f"record {path_rel!r} has no status")
    return status
