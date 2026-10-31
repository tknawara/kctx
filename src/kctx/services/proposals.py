"""Authored proposal lifecycle, distinct from signed knowledge admission.

The pure authored workflow predicate owns readiness and transitions. File
adapters provide conditional publication; the proposal journal recovers paired
Markdown/history writes without claiming cross-file atomic visibility.
"""

import json
import re
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from kctx.adapters.files.mutations import (
    FileRevision,
    compare_and_write,
    file_lock,
    read_revision,
    revision_of,
)
from kctx.adapters.files.storage import atomic_write_json, slugify
from kctx.codecs.documents import MarkdownDocument, read_document, render_document, unfenced_lines
from kctx.codecs.proposals import decode_proposal, proposal_fields
from kctx.domain.ids import (
    ActorId,
    CheckerId,
    GateId,
    ProposalId,
    ProposalMaterialRevision,
    TargetRevision,
)
from kctx.domain.proposals import (
    GateDefinition,
    GateResult,
    GateStatus,
    Proposal,
    ProposalAdded,
    ProposalBackfill,
    ProposalDocument,
    ProposalListing,
    ProposalProfile,
    ProposalShown,
    ProposalUpdated,
)
from kctx.domain.time import iso_now, today
from kctx.domain.vocabulary import (
    GateOutcome,
    GateWhen,
    ProposalKind,
    ProposalOrigin,
    ProposalStatus,
    ProposalType,
)
from kctx.errors import KctxError
from kctx.semantics.model import (
    AuthoredGateDefinition,
    AuthoredGateResult,
    AuthoredProfile,
    AuthoredProposal,
    AuthoredReplacement,
    AuthoredStatus,
)
from kctx.semantics.model import GateOutcome as SemanticOutcome
from kctx.semantics.model import GateWhen as SemanticWhen
from kctx.semantics.workflow import (
    authored_edge,
    authored_gate_passes,
    authored_gate_valid,
    authored_ready,
    authored_transition,
)
from kctx.services import gates as gates_mod
from kctx.services.proposal_mutation import publish, recover
from kctx.services.proposal_targets import resolve_landed, resolve_target

SECTION_ORDER = (
    "Context",
    "Evidence",
    "Proposed change",
    "Research",
    "Alternatives considered",
    "Acceptance gates",
    "Impact",
    "Landing plan",
    "References",
    "Why general / justification",
    "Decision log",
)
DECIDED_STATUSES = frozenset(
    (
        ProposalStatus.ACCEPTED,
        ProposalStatus.REJECTED,
        ProposalStatus.APPLIED,
        ProposalStatus.LANDING,
    )
)
_STATUS = {
    ProposalStatus.DRAFT: AuthoredStatus.DRAFT,
    ProposalStatus.PROPOSED: AuthoredStatus.PROPOSED,
    ProposalStatus.ACCEPTED: AuthoredStatus.ACCEPTED,
    ProposalStatus.REJECTED: AuthoredStatus.REJECTED,
    ProposalStatus.LANDING: AuthoredStatus.LANDING,
    ProposalStatus.APPLIED: AuthoredStatus.APPLIED,
    ProposalStatus.VERIFIED: AuthoredStatus.VERIFIED,
    ProposalStatus.REGRESSED: AuthoredStatus.REGRESSED,
    ProposalStatus.DEFERRED: AuthoredStatus.DEFERRED,
    ProposalStatus.SUPERSEDED: AuthoredStatus.SUPERSEDED,
}
_WHEN = {
    GateWhen.LAND: SemanticWhen.LAND,
    GateWhen.DEPLOY: SemanticWhen.DEPLOY,
    GateWhen.USE: SemanticWhen.USE,
}
_OUTCOME = {
    GateOutcome.PASS: SemanticOutcome.PASS,
    GateOutcome.FAIL: SemanticOutcome.FAIL,
    GateOutcome.UNK: SemanticOutcome.UNKNOWN,
}
_REPO_SHA_RE = re.compile(r"\b([a-zA-Z][\w.-]*)@([0-9a-f]{7,40})\b")


def proposals_root(root: Path) -> Path:
    return root / "proposals"


def _count_bullets(text: str) -> int:
    return sum(
        1
        for line in text.splitlines()
        if line.strip().startswith(("-", "*")) or re.match(r"^\d+[.)]\s", line.strip())
    )


def _actor(value: str | None) -> ActorId | None:
    return ActorId(value) if value and value.strip() else None


def _definition(gate: GateDefinition) -> AuthoredGateDefinition:
    return AuthoredGateDefinition(
        gate.id,
        gate.claim or "",
        gate.check or "",
        _WHEN[gate.when],
        _actor(gate.by),
        CheckerId(gate.checker) if gate.checker and gate.checker.strip() else None,
    )


def material_revision(document: MarkdownDocument) -> ProposalMaterialRevision:
    """Bind authored intent and unknown content, excluding lifecycle bookkeeping."""
    bookkeeping = {
        "status",
        "updated",
        "decided_by",
        "acceptor",
        "executor",
        "verifier",
        "accepted_revision",
        "superseded_by",
        "swept_at",
        "landed",
        "last_actor",
        "regression_note",
    }
    preamble = document.body
    for offset, line in unfenced_lines(document.body):
        if re.match(r"^##\s", line):
            preamble = document.body[:offset]
            break
    value = {
        "frontmatter": {
            key: value for key, value in document.frontmatter.items() if key not in bookkeeping
        },
        "preamble": preamble.replace("\r\n", "\n").replace("\r", "\n"),
        "sections": [
            (name, content.replace("\r\n", "\n").replace("\r", "\n"))
            for name, content in document.sections.items()
            if name != "Decision log"
        ],
    }
    return ProposalMaterialRevision(
        revision_of(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).val
    )


def _context_label(value: str | None) -> str:
    return value if value and value.strip().lower() not in {"unknown", "unk"} else ""


def assessment(
    proposal: Proposal,
    body: Mapping[str, str],
    results: tuple[GateResult, ...] = (),
    *,
    actor: str = "",
    note: str = "",
    document: MarkdownDocument | None = None,
    replacements: tuple[AuthoredReplacement, ...] = (),
    root: Path | None = None,
    resolve_landed_refs: bool = False,
) -> AuthoredProposal:
    bound: list[AuthoredGateResult] = []
    definition_revision = gates_mod.gates_rev(body)
    for result in results:
        if (
            result.definition is None
            or result.target_revision is None
            or result.checker is None
            or result.observed_at is None
            or result.expires_at is None
            or result.proposal_revision is None
            or result.environment is None
            or result.scope is None
            or result.by is None
        ):
            continue
        if result.rev != definition_revision:
            continue
        bound.append(
            AuthoredGateResult(
                _definition(result.definition),
                result.target_revision,
                CheckerId(result.checker),
                _OUTCOME[result.outcome],
                result.observed_at,
                result.expires_at,
                proposal_revision=result.proposal_revision,
                environment=_context_label(result.environment),
                scope=_context_label(result.scope),
                evidence_refs=(result.evidence,),
                actor=ActorId(result.by),
            )
        )
    target = proposal.target_revision
    if root is not None and proposal.target_revision is not None:
        target = resolve_target(root, proposal.target_revision)
    resolved = (
        resolve_landed(root, proposal.landed) if root is not None and resolve_landed_refs else ()
    )
    return AuthoredProposal(
        _STATUS[proposal.status],
        AuthoredProfile.MODERN
        if proposal.profile is ProposalProfile.MODERN
        else AuthoredProfile.LEGACY_LIMITED,
        bool(body.get("Research", "").strip()),
        _count_bullets(body.get("Alternatives considered", "")),
        target,
        tuple(_definition(gate) for gate in gates_mod.parse_gates_table(body)),
        tuple(bound),
        _actor(actor),
        _actor(proposal.acceptor),
        _actor(proposal.executor),
        _actor(proposal.verifier),
        proposal.landed,
        note,
        proposal.id,
        proposal.superseded_by,
        replacements,
        proposal.accepted_revision,
        material_revision(
            document
            if document is not None
            else render_document(proposal_fields(proposal), body, title=proposal.title)
        ),
        environment=_context_label(proposal.environment),
        scope=_context_label(proposal.scope),
        resolved_landed=resolved,
    )


def persisted_assessment(
    proposal: Proposal,
    document: MarkdownDocument,
    results: tuple[GateResult, ...] = (),
    *,
    replacements: tuple[AuthoredReplacement, ...] = (),
    root: Path | None = None,
) -> AuthoredProposal:
    """Project stored attribution without inventing actors or verification evidence."""
    actor = proposal.last_actor or proposal.decided_by or ""
    note = proposal.regression_note or ""
    if not note and proposal.profile is ProposalProfile.LEGACY_LIMITED:
        for line in reversed(document.sections.get("Decision log", "").splitlines()):
            if re.match(r"^- \d{4}-\d{2}-\d{2}: regressed\b", line):
                _, separator, detail = line.partition(" — ")
                note = detail if separator else ""
                break
    return assessment(
        proposal,
        document.sections,
        results,
        actor=actor,
        note=note,
        document=document,
        replacements=replacements,
        root=root,
        resolve_landed_refs=proposal.status in (ProposalStatus.APPLIED, ProposalStatus.VERIFIED),
    )


def review_gate_missing(body: Mapping[str, str]) -> tuple[str, ...]:
    """Diagnostics for the same primitive requirements used by authored_ready."""
    missing: list[str] = []
    if not body.get("Research", "").strip():
        missing.append("Research (or a one-line justified skip)")
    if _count_bullets(body.get("Alternatives considered", "")) < 2:
        missing.append("Alternatives considered (at least 2)")
    table = gates_mod.parse_gates_table(body)
    if not table or not all(authored_gate_valid(_definition(gate)) for gate in table):
        missing.append("Acceptance gates (a runnable-checks table)")
    return tuple(missing)


def add(
    root: Path,
    *,
    kind: ProposalKind,
    origin: ProposalOrigin,
    title: str,
    context: str,
    evidence: str,
    change: str,
    why: str,
    target: tuple[str, ...] | None = None,
    type: ProposalType | tuple[ProposalType, ...] | None = None,
    references: tuple[str, ...] | None = None,
    project: str | None = None,
    source_session: str | None = None,
    proposed_by: str | None = None,
    requested_by: str | None = None,
    research: str = "",
    alternatives: str = "",
    gates: str = "",
    impact: str = "",
    plan: str = "",
    force: bool = False,
    target_revision: TargetRevision | None = None,
    environment: str | None = None,
    scope: str | None = None,
) -> ProposalAdded:
    created = today()
    home = proposals_root(root) / kind.value / f"{created}-{slugify(title)}"
    path = home / "proposal.md"
    identity = ProposalId(f"{kind.value}/{created}-{slugify(title)}")
    body = {
        "Context": context,
        "Evidence": evidence,
        "Proposed change": change,
        "Research": research,
        "Alternatives considered": alternatives,
        "Acceptance gates": gates,
        "Impact": impact,
        "Landing plan": plan,
        "References": "\n".join(f"- {reference}" for reference in references or ()),
        "Why general / justification": why,
        "Decision log": "",
    }
    proposal = Proposal(
        identity,
        kind,
        title,
        ProposalStatus.DRAFT,
        created,
        origin,
        target or (),
        type,
        created,
        proposed_by,
        requested_by,
        source_session,
        project,
        references=references or (),
        target_revision=target_revision,
        environment=environment,
        scope=scope,
    )
    missing = review_gate_missing(body)
    if authored_ready(assessment(proposal, body)):
        proposal = replace(proposal, status=ProposalStatus.PROPOSED)
    body["Decision log"] = f"- {created}: {proposal.status.value}" + (
        f" — missing for review: {', '.join(missing)}" if missing else ""
    )
    document = render_document(proposal_fields(proposal), body, title=title)
    proposal = decode_proposal(document)
    with file_lock(path):
        recover(path)
        previous = read_revision(path)
        if previous is not None and not force:
            raise KctxError("conflict", f"proposal {identity} already exists (use --force)")
        (home / "research").mkdir(exist_ok=True)
        (home / "evidence").mkdir(exist_ok=True)
        if not (home / "gates.json").exists():
            atomic_write_json(home / "gates.json", [])
        compare_and_write(path, document.text.encode("utf-8"), expected=previous)
    return ProposalAdded(identity, path, proposal, missing)


def all_paths(root: Path) -> tuple[Path, ...]:
    base = proposals_root(root)
    if not base.exists():
        return ()
    paths: list[Path] = []
    for directory in sorted(path for path in base.iterdir() if path.is_dir()):
        if directory.name.startswith("."):
            continue
        for item in sorted(directory.iterdir()):
            if item.is_file() and item.suffix == ".md":
                paths.append(item)
            elif item.is_dir() and (item / "proposal.md").exists():
                paths.append(item / "proposal.md")
    return tuple(paths)


def _read(path: Path) -> ProposalDocument:
    document = read_document(path)
    profile = (
        ProposalProfile.MODERN if path.name == "proposal.md" else ProposalProfile.LEGACY_LIMITED
    )
    proposal = decode_proposal(document, profile=profile)
    if profile is ProposalProfile.MODERN and proposal.profile is ProposalProfile.LEGACY_LIMITED:
        raise KctxError("malformed", "directory-home proposal cannot claim a legacy profile")
    return ProposalDocument(path, proposal, document)


def load(root: Path, proposal_id: ProposalId) -> ProposalDocument:
    for path in all_paths(root):
        with file_lock(path):
            recover(path)
            found = _read(path)
        if found.proposal.id == proposal_id:
            return found
    raise KctxError("not-found", f"proposal {proposal_id} not found")


@contextmanager
def _locked(
    root: Path, proposal_id: ProposalId, expected: FileRevision | None
) -> Iterator[ProposalDocument]:
    before = load(root, proposal_id)
    predecessor = expected or FileRevision(before.revision)
    with file_lock(before.path):
        recover(before.path)
        if read_revision(before.path) != predecessor:
            raise KctxError("conflict", "proposal changed since the expected predecessor")
        yield _read(before.path)


def replacement_snapshot(
    root: Path, candidate: Proposal, candidate_path: Path
) -> tuple[AuthoredReplacement, ...]:
    """Caller holds the collection lock; other proposals retain their current edges."""
    records: list[AuthoredReplacement] = []
    for path in all_paths(root):
        if path == candidate_path:
            record = candidate
        else:
            with file_lock(path):
                recover(path)
                record = _read(path).proposal
        records.append(AuthoredReplacement(record.id, record.superseded_by))
    return tuple(records)


def list_proposals(
    root: Path,
    *,
    status: ProposalStatus | None = None,
    kind: ProposalKind | None = None,
    pending_gates: bool = False,
) -> tuple[ProposalListing, ...]:
    listings: list[ProposalListing] = []
    for path in all_paths(root):
        with file_lock(path):
            recover(path)
            found = _read(path)
            proposal = found.proposal
            if (status is not None and proposal.status is not status) or (
                kind is not None and proposal.kind is not kind
            ):
                continue
            pending: tuple[GateId, ...] = ()
            if pending_gates:
                if proposal.status is not ProposalStatus.APPLIED:
                    continue
                model = assessment(
                    proposal,
                    found.document.sections,
                    gates_mod.load_results(path),
                    document=found.document,
                    root=root,
                )
                pending = tuple(
                    gate.id
                    for gate in model.gate_definitions
                    if gate.when in (SemanticWhen.DEPLOY, SemanticWhen.USE)
                    and not authored_gate_passes(model, gate, int(time.time()))
                )
                if not pending:
                    continue
            listings.append(ProposalListing(proposal, pending))
    return tuple(listings)


def show(root: Path, proposal_id: ProposalId) -> ProposalShown:
    with _locked(root, proposal_id, None) as found:
        table = gates_mod.parse_gates_table(found.document.sections)
        results = gates_mod.load_results(found.path)
        model = assessment(
            found.proposal,
            found.document.sections,
            results,
            document=found.document,
            root=root if results else None,
        )
        statuses: list[GateStatus] = []
        now = int(time.time())
        outcomes = {value: key for key, value in _OUTCOME.items()}
        for gate in table:
            definition = _definition(gate)
            latest = next(
                (
                    result
                    for result in reversed(model.gate_results)
                    if result.definition == definition
                    and result.target_revision == model.target_revision
                    and result.proposal_revision == model.proposal_revision
                    and result.environment == model.environment
                    and result.scope == model.scope
                    and result.environment.strip()
                    and result.scope.strip()
                    and result.evidence_refs
                    and all(reference.strip() for reference in result.evidence_refs)
                    and (definition.checker is None or result.checker == definition.checker)
                    and result.observed_at <= now
                ),
                None,
            )
            outcome = (
                outcomes[latest.result]
                if latest is not None and now <= latest.expires_at
                else GateOutcome.UNK
            )
            statuses.append(GateStatus(gate, outcome))
        return ProposalShown(
            found.proposal.id,
            found.proposal,
            tuple(section for section in SECTION_ORDER if section in found.document.sections),
            tuple(statuses),
            found.revision,
        )


def set_status(
    root: Path,
    proposal_id: ProposalId,
    *,
    status: ProposalStatus | None = None,
    by: str | None = None,
    note: str | None = None,
    superseded_by: ProposalId | None = None,
    origin: ProposalOrigin | None = None,
    proposed_by: str | None = None,
    requested_by: str | None = None,
    swept_at: str | None = None,
    landed_add: tuple[str, ...] | None = None,
    target_revision: TargetRevision | None = None,
    expected_revision: FileRevision | None = None,
    environment: str | None = None,
    scope: str | None = None,
) -> ProposalUpdated:
    with (
        file_lock(proposals_root(root) / ".collection"),
        _locked(root, proposal_id, expected_revision) as found,
    ):
        proposal, document = found.proposal, found.document
        changes: dict[str, str | None] = {"updated": today(), "profile": proposal.profile.value}
        if origin is not None:
            changes["origin"] = origin.value
        for key, value in (
            ("proposed_by", proposed_by),
            ("requested_by", requested_by),
            ("swept_at", swept_at),
            ("environment", environment),
            ("scope", scope),
        ):
            if value is not None:
                changes[key] = value
        if target_revision is not None:
            changes["target_revision"] = target_revision.val
        if landed_add:
            changes["landed"] = (
                "[" + ", ".join(dict.fromkeys((*proposal.landed, *landed_add))) + "]"
            )
        if status is not None:
            changes["last_actor"] = by
            if status is ProposalStatus.REGRESSED:
                changes["regression_note"] = note
            if not authored_edge(_STATUS[proposal.status], _STATUS[status]):
                raise KctxError(
                    "malformed", f"illegal transition {proposal.status.value!r} -> {status.value!r}"
                )
            if status in DECIDED_STATUSES and (not by or not by.strip()):
                raise KctxError("incomplete", f"status={status.value!r} requires --by")
            if status is ProposalStatus.ACCEPTED:
                changes["acceptor"] = by
                if not proposal.decided_by:
                    changes["decided_by"] = by
            if status is ProposalStatus.LANDING:
                changes["executor"] = by
                if (
                    not proposal.acceptor
                    and proposal.status is ProposalStatus.ACCEPTED
                    and proposal.decided_by
                ):
                    changes["acceptor"] = proposal.decided_by
            if status is ProposalStatus.VERIFIED and by:
                changes["verifier"] = by
            if status is ProposalStatus.REJECTED and not proposal.decided_by:
                changes["decided_by"] = by
            if superseded_by is not None:
                if status is not ProposalStatus.SUPERSEDED:
                    raise KctxError("malformed", "--superseded-by requires status=superseded")
                changes["superseded_by"] = superseded_by.val
            # All same-command fields, including landed additions, precede validation.
            candidate = document.update_fields(changes)
            if status is ProposalStatus.ACCEPTED:
                candidate = candidate.update_fields(
                    {"accepted_revision": material_revision(candidate).val}
                )
            admitted = decode_proposal(candidate)
            replacements = (
                replacement_snapshot(root, admitted, found.path)
                if status is ProposalStatus.SUPERSEDED
                else ()
            )
            model = assessment(
                admitted,
                candidate.sections,
                gates_mod.load_results(found.path),
                actor=by or "",
                note=note or "",
                document=candidate,
                replacements=replacements,
                root=root if status in (ProposalStatus.APPLIED, ProposalStatus.VERIFIED) else None,
                resolve_landed_refs=status in (ProposalStatus.APPLIED, ProposalStatus.VERIFIED),
            )
            if not authored_transition(model, _STATUS[status], int(time.time())):
                missing = (
                    review_gate_missing(candidate.sections)
                    if proposal.profile is ProposalProfile.MODERN
                    else ()
                )
                detail = "; missing for review: " + ", ".join(missing) if missing else ""
                raise KctxError(
                    "incomplete",
                    f"authored transition {proposal.status.value!r} -> {status.value!r} rejected: readiness, actors, landed references, or current bound gates do not satisfy policy{detail}",
                )
            candidate = candidate.update_fields({"status": status.value}).append_section(
                "Decision log",
                f"- {today()}: {status.value}"
                + (f" by {by}" if by else "")
                + (f" — {note}" if note else ""),
            )
        else:
            if not any(
                value is not None
                for value in (
                    origin,
                    proposed_by,
                    requested_by,
                    swept_at,
                    landed_add,
                    target_revision,
                    environment,
                    scope,
                )
            ):
                raise KctxError(
                    "incomplete", "set requires --status or at least one field to update"
                )
            candidate = document.update_fields(changes)
        admitted = decode_proposal(candidate)
        publish(found, candidate.text)
        warnings = (
            (
                "legacy_limited authored profile: historical status is not verified knowledge or release authority",
            )
            if proposal.profile is ProposalProfile.LEGACY_LIMITED
            else ()
        )
        return ProposalUpdated(admitted, warnings)


def gate(
    root: Path,
    proposal_id: ProposalId,
    gate_id: GateId,
    *,
    outcome: GateOutcome,
    evidence: str,
    by: str | None = None,
    rev: str | None = None,
    target_revision: TargetRevision | None = None,
    checker: str | None = None,
    expires_at: int | None = None,
    expected_revision: FileRevision | None = None,
    environment: str | None = None,
    scope: str | None = None,
) -> GateResult:
    with _locked(root, proposal_id, expected_revision) as found:
        table = gates_mod.parse_gates_table(found.document.sections)
        definition = next((item for item in table if item.id == gate_id), None)
        if definition is None:
            raise KctxError(
                "not-found",
                f"gate {gate_id.val!r} not declared in {proposal_id}'s Acceptance gates table",
            )
        target = target_revision or found.proposal.target_revision
        bound_environment = _context_label(
            environment if environment is not None else found.proposal.environment
        )
        bound_scope = _context_label(scope if scope is not None else found.proposal.scope)
        if not bound_environment or not bound_scope:
            raise KctxError("incomplete", "gate requires explicit known environment and scope")
        now = int(time.time())
        if (
            target is None
            or not checker
            or not checker.strip()
            or expires_at is None
            or expires_at < now
        ):
            raise KctxError(
                "incomplete",
                "gate requires target revision, explicit checker and unexpired --expires-at",
            )
        if not authored_gate_valid(_definition(definition)) or (
            definition.checker and checker != definition.checker
        ):
            raise KctxError(
                "malformed",
                "gate definition/checker is incomplete or does not match the declared checker",
            )
        if not evidence.strip() or not by or not by.strip():
            raise KctxError("incomplete", "gate requires evidence and recording actor --by")
        target = resolve_target(root, target)
        entry = GateResult(
            gate_id,
            outcome,
            evidence,
            iso_now(),
            by,
            rev or gates_mod.gates_rev(found.document.sections),
            target,
            checker,
            now,
            expires_at,
            definition,
            material_revision(found.document),
            bound_environment,
            bound_scope,
        )
        line = f"- {today()}: gate {gate_id.val} -> {outcome.value} by {by} ({evidence})"
        candidate = found.document.append_section("Decision log", line).update_fields(
            {"updated": today(), "profile": found.proposal.profile.value}
        )
        decode_proposal(candidate)
        publish(found, candidate.text, (*gates_mod.load_results(found.path), entry))
        return entry


def backfill_landed_from_notes(
    root: Path, *, dry_run: bool = False
) -> tuple[ProposalBackfill, ...]:
    changed: list[ProposalBackfill] = []
    for path in all_paths(root):
        with file_lock(path):
            recover(path)
            found = _read(path)
            if (
                found.proposal.status not in (ProposalStatus.APPLIED, ProposalStatus.VERIFIED)
                or found.proposal.landed
            ):
                continue
            tokens = tuple(
                dict.fromkeys(
                    f"{match[1]}@{match[2]}"
                    for match in _REPO_SHA_RE.finditer(
                        found.document.sections.get("Decision log", "")
                    )
                )
            )
            if not tokens:
                continue
            changed.append(ProposalBackfill(found.proposal.id, path, tokens))
            if not dry_run:
                publish(
                    found,
                    found.document.update_fields(
                        {
                            "landed": "[" + ", ".join(tokens) + "]",
                            "profile": found.proposal.profile.value,
                        }
                    ).text,
                )
    return tuple(changed)
