"""Proposal admission and explicit command-wire rendering."""

from collections.abc import Mapping
from enum import Enum
from typing import TypeVar

from kctx.codecs.documents import MarkdownDocument
from kctx.codecs.frontmatter import split_list_value
from kctx.domain.ids import ActorId, ProposalId, ProposalMaterialRevision, SourceId, TargetRevision
from kctx.domain.json import texts
from kctx.domain.proposals import (
    Proposal,
    ProposalAdded,
    ProposalBackfill,
    ProposalListing,
    ProposalProfile,
    ProposalShown,
    ProposalUpdated,
)
from kctx.domain.vocabulary import ProposalKind, ProposalOrigin, ProposalStatus, ProposalType
from kctx.errors import KctxError
from kctx.semantics.workflow_models import ImplementationBinding

BINDING_FIELDS = (
    "binding_design_revision",
    "binding_source",
    "binding_target_revision",
    "binding_actor",
    "binding_observed_at",
)


def binding_fields(binding: ImplementationBinding | None) -> dict[str, str | None]:
    if binding is None:
        return dict.fromkeys(BINDING_FIELDS)
    return {
        "binding_design_revision": binding.design_revision.val,
        "binding_source": binding.source.val,
        "binding_target_revision": binding.target_revision.val,
        "binding_actor": binding.actor.val,
        "binding_observed_at": str(binding.observed_at),
    }


def _decode_binding(fm: Mapping[str, str]) -> ImplementationBinding | None:
    present = [key in fm for key in BINDING_FIELDS]
    if not any(present) or (all(present) and not any(fm[key] for key in BINDING_FIELDS)):
        return None
    if not all(present) or not all(fm[key].strip() for key in BINDING_FIELDS):
        raise KctxError("malformed", "implementation binding requires all five flat fields")
    observed = fm["binding_observed_at"]
    if not observed.isascii() or not observed.isdigit():
        raise KctxError("malformed", "binding_observed_at must be a nonnegative integer")
    try:
        return ImplementationBinding(
            ProposalMaterialRevision(fm["binding_design_revision"]),
            SourceId(fm["binding_source"]),
            TargetRevision(fm["binding_target_revision"]),
            ActorId(fm["binding_actor"]),
            int(observed),
        )
    except ValueError as exc:
        raise KctxError("malformed", str(exc)) from exc


E = TypeVar("E", bound=Enum)


def _enum(kind: type[E], raw: str, field: str) -> E:
    try:
        return kind(raw)
    except ValueError as exc:
        raise KctxError("malformed", f"invalid proposal {field}: {raw!r}") from exc


def decode_proposal(
    document: MarkdownDocument, *, profile: ProposalProfile = ProposalProfile.MODERN
) -> Proposal:
    fm = document.frontmatter
    for key in ("id", "kind", "title", "status", "created"):
        if not fm.get(key):
            raise KctxError("malformed", f"proposal missing required field {key!r}")
    version = fm.get("schema_version")
    if version is not None and version != "1":
        raise KctxError("malformed", f"unsupported proposal schema_version {version!r}")
    workflow = fm.get("workflow_version", "2")
    if workflow not in ("2", "3"):
        raise KctxError("malformed", f"unsupported proposal workflow_version {workflow!r}")
    # Under workflow2 these names were ordinary unknown authored material, not
    # execution authority. Preserve their bytes/digest without interpreting them.
    source = fm.get("target_source") if workflow == "3" else None
    if workflow == "3" and (not source or source.strip().lower() in {"unknown", "unk"}):
        raise KctxError("malformed", "workflow3 requires explicit known target_source")
    for key in ("target", "references", "landed"):
        value = fm.get(key, "")
        if value and not (value.startswith("[") and value.endswith("]")):
            raise KctxError("malformed", f"proposal {key!r} must be a bracketed list")
    raw_type = fm.get("type", "")
    types: ProposalType | tuple[ProposalType, ...] | None = None
    if raw_type.startswith("["):
        if not raw_type.endswith("]"):
            raise KctxError("malformed", "unterminated proposal type list")
        types = tuple(_enum(ProposalType, value, "type") for value in split_list_value(raw_type))
    elif raw_type:
        types = _enum(ProposalType, raw_type, "type")
    try:
        identity = ProposalId(fm["id"])
        superseded = ProposalId(fm["superseded_by"]) if fm.get("superseded_by") else None
    except ValueError as exc:
        raise KctxError("malformed", str(exc)) from exc
    return Proposal(
        id=identity,
        kind=_enum(ProposalKind, fm["kind"], "kind"),
        title=fm["title"],
        status=_enum(ProposalStatus, fm["status"], "status"),
        created=fm["created"],
        origin=_enum(ProposalOrigin, fm["origin"], "origin") if fm.get("origin") else None,
        target=tuple(split_list_value(fm.get("target", ""))),
        type=types,
        updated=fm.get("updated") or None,
        proposed_by=fm.get("proposed_by") or None,
        requested_by=fm.get("requested_by") or None,
        source_session=fm.get("source_session") or None,
        project=fm.get("project") or None,
        swept_at=fm.get("swept_at") or None,
        references=tuple(split_list_value(fm.get("references", ""))),
        landed=tuple(split_list_value(fm.get("landed", ""))),
        decided_by=fm.get("decided_by") or None,
        superseded_by=superseded,
        profile=_enum(ProposalProfile, fm.get("profile", profile.value), "profile"),
        target_revision=TargetRevision(fm["target_revision"])
        if fm.get("target_revision")
        else None,
        acceptor=fm.get("acceptor") or None,
        executor=fm.get("executor") or None,
        verifier=fm.get("verifier") or None,
        accepted_revision=ProposalMaterialRevision(fm["accepted_revision"])
        if fm.get("accepted_revision")
        else None,
        environment=fm.get("environment") or None,
        scope=fm.get("scope") or None,
        last_actor=fm.get("last_actor") or None,
        regression_note=fm.get("regression_note") or None,
        workflow_version=int(workflow),
        target_source=SourceId(source) if source else None,
        binding=_decode_binding(fm) if workflow == "3" else None,
    )


def encode_proposal(proposal: Proposal) -> dict[str, object]:
    types = proposal.type
    return {
        "id": proposal.id.val,
        "kind": proposal.kind.value,
        "type": [value.value for value in types]
        if isinstance(types, tuple)
        else types.value
        if types
        else None,
        "title": proposal.title,
        "status": proposal.status.value,
        "created": proposal.created,
        "updated": proposal.updated,
        "origin": proposal.origin.value if proposal.origin else None,
        "proposed_by": proposal.proposed_by,
        "requested_by": proposal.requested_by,
        "source_session": proposal.source_session,
        "project": proposal.project,
        "swept_at": proposal.swept_at,
        "target": list(proposal.target),
        "references": list(proposal.references),
        "landed": list(proposal.landed),
        "decided_by": proposal.decided_by,
        "superseded_by": proposal.superseded_by.val if proposal.superseded_by else None,
        "profile": proposal.profile.value,
        "target_revision": proposal.target_revision.val
        if proposal.target_revision is not None
        else None,
        "acceptor": proposal.acceptor,
        "executor": proposal.executor,
        "verifier": proposal.verifier,
        "accepted_revision": proposal.accepted_revision.val
        if proposal.accepted_revision is not None
        else None,
        "environment": proposal.environment,
        "scope": proposal.scope,
        "last_actor": proposal.last_actor,
        "regression_note": proposal.regression_note,
        "workflow_version": proposal.workflow_version,
        "target_source": proposal.target_source.val if proposal.target_source is not None else None,
        "binding": {
            "design_revision": proposal.binding.design_revision.val,
            "source": proposal.binding.source.val,
            "target_revision": proposal.binding.target_revision.val,
            "actor": proposal.binding.actor.val,
            "observed_at": proposal.binding.observed_at,
        }
        if proposal.binding is not None
        else None,
    }


def proposal_fields(proposal: Proposal) -> dict[str, str | None]:
    wire = encode_proposal(proposal)
    wire.pop("binding")
    if proposal.workflow_version == 2:
        wire.pop("workflow_version")
        wire.pop("target_source")
    fields: dict[str, str | None] = {}
    for key, value in wire.items():
        if value is None or isinstance(value, str):
            fields[key] = value
        elif isinstance(value, int):
            fields[key] = str(value)
        else:
            fields[key] = "[" + ", ".join(texts(value, key)) + "]"
    if proposal.workflow_version == 3:
        fields["schema_version"] = "1"
        fields.update(binding_fields(proposal.binding))
    return fields


def encode_added(result: ProposalAdded) -> dict[str, object]:
    wire: dict[str, object] = {
        "id": result.id.val,
        "path": str(result.path),
        "frontmatter": encode_proposal(result.proposal),
    }
    if result.missing:
        wire["missing"] = list(result.missing)
    return wire


def encode_updated(result: ProposalUpdated) -> dict[str, object]:
    wire = encode_proposal(result.proposal)
    if result.warnings:
        wire["warnings"] = list(result.warnings)
    return wire


def encode_listing(result: ProposalListing) -> dict[str, object]:
    wire = encode_proposal(result.proposal)
    if result.pending_gates:
        wire["pending_gates"] = [identity.val for identity in result.pending_gates]
    return wire


def encode_shown(result: ProposalShown) -> dict[str, object]:
    from kctx.codecs.gates import encode_gate_definition

    return {
        "id": result.id.val,
        "revision": result.revision,
        "frontmatter": encode_proposal(result.proposal),
        "sections": list(result.sections),
        "gates": [
            {**encode_gate_definition(gate.definition), "outcome": gate.outcome.value}
            for gate in result.gates
        ],
    }


def encode_backfill(result: ProposalBackfill) -> dict[str, object]:
    return {"id": result.id.val, "path": str(result.path), "landed": list(result.landed)}
