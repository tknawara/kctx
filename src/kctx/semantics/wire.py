"""Strict v2 boundary. No fixture flags, caller digests, or implicit versions.

Direct tagged decoders reject missing or malformed discriminants with
``ValueError("invalid_request")`` before selecting a constructor.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from typing import TypeGuard, TypeVar

from kctx.domain.ids import (
    ActorId,
    AttestationId,
    CheckerId,
    ClaimId,
    ClaimRevision,
    ContentId,
    CorrectionId,
    DerivationId,
    EnumerationId,
    GateId,
    ObservationId,
    OperationId,
    PolicyId,
    ProjectId,
    ProposalId,
    ProposalMaterialRevision,
    ReceiptId,
    RuleVersion,
    SnapshotId,
    SourceId,
    SourceRevision,
    TargetRevision,
)
from kctx.errors import KctxError
from kctx.semantics import model as M
from kctx.semantics.checker import assess, check, context_matches, reusable, supported
from kctx.semantics.time import assess_fresh
from kctx.semantics.wellformed import context_wf, well_formed
from kctx.semantics.workflow import (
    apply_plan,
    apply_selection,
    authored_candidate_valid,
    authored_transition,
    conclude,
    transition,
)

T = TypeVar("T")


def _is_raw_object(value: object) -> TypeGuard[dict[object, object]]:
    return isinstance(value, dict)


def is_object(value: object) -> TypeGuard[dict[str, object]]:
    return _is_raw_object(value) and all(isinstance(key, str) for key in value)


def obj(value: object, fields: str | None = None) -> dict[str, object]:
    if not is_object(value) or (fields is not None and set(value) != set(fields.split())):
        raise ValueError("invalid_request")
    return value


def _unicode_scalars(value: str) -> bool:
    return all(not 0xD800 <= ord(character) <= 0xDFFF for character in value)


def text(value: object) -> str:
    if not isinstance(value, str) or not _unicode_scalars(value):
        raise ValueError("invalid_request")
    return value


def nonempty(value: object) -> str:
    result = text(value)
    if not result:
        raise ValueError("invalid_request")
    return result


def nat(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("invalid_request")
    return value


def boolean(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError("invalid_request")
    return value


def is_array(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def items(value: object, decode: Callable[[object], T]) -> tuple[T, ...]:
    if not is_array(value):
        raise ValueError("invalid_request")
    return tuple(decode(item) for item in value)


def optional_identity(value: object, decode: Callable[[str], T]) -> T | None:
    raw = text(value)
    return None if raw == "" else decode(raw)


def enc_optional_identity(
    value: ActorId | CheckerId | ProposalMaterialRevision | TargetRevision | None,
) -> str:
    return "" if value is None else value.val


def dec_scope(value: object) -> M.Scope:
    v = obj(value, "project selector")
    return M.Scope(ProjectId(nonempty(v["project"])), text(v["selector"]))


def enc_scope(value: M.Scope) -> dict[str, object]:
    return {"project": value.project.val, "selector": value.selector}


MAX_TREE_DEPTH = 256


def dec_formula(value: object) -> M.Formula:
    return _dec_formula(value, MAX_TREE_DEPTH)


def _dec_formula(value: object, remaining: int) -> M.Formula:
    if remaining == 0:
        raise ValueError("invalid_request")
    v = obj(value)
    tag = text(v.get("tag"))
    if tag == "atom":
        obj(v, "tag atom")
        a = obj(v["atom"], "subject predicate args")
        return M.Atomic(
            M.Atom(nonempty(a["subject"]), nonempty(a["predicate"]), items(a["args"], text))
        )
    if tag == "truth":
        obj(v, "tag")
        return M.Truth()
    if tag == "and":
        obj(v, "tag left right")
        return M.Conjunction(
            _dec_formula(v["left"], remaining - 1), _dec_formula(v["right"], remaining - 1)
        )
    if tag == "all":
        obj(v, "tag enumeration predicate")
        return M.All(EnumerationId(text(v["enumeration"])), nonempty(v["predicate"]))
    if tag == "inventory":
        obj(v, "tag enumeration")
        return M.Inventory(EnumerationId(text(v["enumeration"])))
    if tag == "absent":
        obj(v, "tag enumeration")
        return M.Absent(EnumerationId(text(v["enumeration"])))
    raise ValueError("invalid_request")


def enc_formula(value: M.Formula) -> dict[str, object]:
    if isinstance(value, M.Atomic):
        return {
            "tag": "atom",
            "atom": {
                "subject": value.atom.subject,
                "predicate": value.atom.predicate,
                "args": list(value.atom.args),
            },
        }
    if isinstance(value, M.Truth):
        return {"tag": "truth"}
    if isinstance(value, M.Conjunction):
        return {"tag": "and", "left": enc_formula(value.left), "right": enc_formula(value.right)}
    if isinstance(value, M.All):
        return {"tag": "all", "enumeration": value.enumeration.val, "predicate": value.predicate}
    if isinstance(value, M.Inventory):
        return {"tag": "inventory", "enumeration": value.enumeration.val}
    return {"tag": "absent", "enumeration": value.enumeration.val}


def dec_statement(value: object) -> M.Statement:
    v = obj(value, "formula scope polarity")
    result = M.Statement(
        dec_formula(v["formula"]), dec_scope(v["scope"]), M.Polarity(text(v["polarity"]))
    )
    if result.polarity is M.Polarity.NEGATIVE and not isinstance(result.formula, M.Atomic):
        raise ValueError("invalid_request")
    return result


def enc_statement(value: M.Statement) -> dict[str, object]:
    return {
        "formula": enc_formula(value.formula),
        "scope": enc_scope(value.scope),
        "polarity": value.polarity.value,
    }


def dec_ref(value: object) -> M.ClaimRef:
    v = obj(value, "id revision")
    return M.ClaimRef(ClaimId(text(v["id"])), ClaimRevision(text(v["revision"])))


def enc_ref(value: M.ClaimRef) -> dict[str, object]:
    return {"id": value.id.val, "revision": value.rev.val}


def dec_claim(value: object) -> M.Claim:
    v = obj(value, "id revision statement")
    return M.Claim(
        ClaimId(text(v["id"])), ClaimRevision(text(v["revision"])), dec_statement(v["statement"])
    )


def enc_claim(value: M.Claim) -> dict[str, object]:
    return {
        "id": value.id.val,
        "revision": value.revision.val,
        "statement": enc_statement(value.statement),
    }


def dec_observation(value: object) -> M.Observation:
    v = obj(value, "id source revision content observed_at outcome")
    return M.Observation(
        ObservationId(text(v["id"])),
        SourceId(nonempty(v["source"])),
        SourceRevision(nonempty(v["revision"])),
        ContentId(nonempty(v["content"])),
        nat(v["observed_at"]),
        M.ObsOutcome(text(v["outcome"])),
    )


def enc_observation(value: M.Observation) -> dict[str, object]:
    return {
        "id": value.id.val,
        "source": value.source.val,
        "revision": value.revision.val,
        "content": value.content.val,
        "observed_at": value.observed_at,
        "outcome": value.outcome.value,
    }


def dec_attestation(value: object) -> M.Attestation:
    v = obj(value, "id claim observation statement authority")
    result = M.Attestation(
        AttestationId(text(v["id"])),
        dec_ref(v["claim"]),
        ObservationId(text(v["observation"])),
        dec_statement(v["statement"]),
        ActorId(nonempty(v["authority"])),
    )
    if not isinstance(result.statement.formula, (M.Atomic, M.Inventory)):
        raise ValueError("invalid_request")
    return result


def enc_attestation(value: M.Attestation) -> dict[str, object]:
    return {
        "id": value.id.val,
        "claim": enc_ref(value.claim),
        "observation": value.observation.val,
        "statement": enc_statement(value.statement),
        "authority": value.authority.val,
    }


def dec_enumeration(value: object) -> M.Enumeration:
    v = obj(value, "id source revision query scope observation members universe method")
    return M.Enumeration(
        EnumerationId(text(v["id"])),
        SourceId(nonempty(v["source"])),
        SourceRevision(nonempty(v["revision"])),
        nonempty(v["query"]),
        dec_scope(v["scope"]),
        ObservationId(text(v["observation"])),
        items(v["members"], nonempty),
        items(v["universe"], nonempty),
        nonempty(v["method"]),
    )


def enc_enumeration(value: M.Enumeration) -> dict[str, object]:
    return {
        "id": value.id.val,
        "source": value.source.val,
        "revision": value.revision.val,
        "query": value.query,
        "scope": enc_scope(value.scope),
        "observation": value.observation.val,
        "members": list(value.members),
        "universe": list(value.universe),
        "method": value.method,
    }


def dec_witness(value: object) -> M.Witness:
    return _dec_witness(value, MAX_TREE_DEPTH)


def _dec_witness(value: object, remaining: int) -> M.Witness:
    if remaining == 0:
        raise ValueError("invalid_request")
    v = obj(value)
    tag = text(v.get("tag"))
    if tag == "attest":
        obj(v, "tag attestation")
        return M.AttestWitness(AttestationId(text(v["attestation"])))
    if tag == "truth":
        obj(v, "tag scope")
        return M.TruthWitness(dec_scope(v["scope"]))
    if tag == "and":
        obj(v, "tag left right")
        return M.AndWitness(
            _dec_witness(v["left"], remaining - 1), _dec_witness(v["right"], remaining - 1)
        )
    if tag == "specialize":
        obj(v, "tag scope premise")
        return M.SpecializeWitness(dec_scope(v["scope"]), _dec_witness(v["premise"], remaining - 1))
    if tag == "all":
        obj(v, "tag enumeration predicate premise")
        return M.AllWitness(
            EnumerationId(text(v["enumeration"])),
            nonempty(v["predicate"]),
            _dec_witness(v["premise"], remaining - 1),
        )
    if tag == "absent":
        obj(v, "tag enumeration premise")
        return M.AbsentWitness(
            EnumerationId(text(v["enumeration"])), _dec_witness(v["premise"], remaining - 1)
        )
    raise ValueError("invalid_request")


def enc_witness(value: M.Witness) -> dict[str, object]:
    if isinstance(value, M.AttestWitness):
        return {"tag": "attest", "attestation": value.attestation.val}
    if isinstance(value, M.TruthWitness):
        return {"tag": "truth", "scope": enc_scope(value.scope)}
    if isinstance(value, M.AndWitness):
        return {"tag": "and", "left": enc_witness(value.left), "right": enc_witness(value.right)}
    if isinstance(value, M.SpecializeWitness):
        return {
            "tag": "specialize",
            "scope": enc_scope(value.scope),
            "premise": enc_witness(value.premise),
        }
    if isinstance(value, M.AllWitness):
        return {
            "tag": "all",
            "enumeration": value.enumeration.val,
            "predicate": value.predicate,
            "premise": enc_witness(value.premise),
        }
    return {
        "tag": "absent",
        "enumeration": value.enumeration.val,
        "premise": enc_witness(value.premise),
    }


def dec_derivation(value: object) -> M.Derivation:
    v = obj(value, "id claim witness")
    return M.Derivation(DerivationId(text(v["id"])), dec_ref(v["claim"]), dec_witness(v["witness"]))


def enc_derivation(value: M.Derivation) -> dict[str, object]:
    return {
        "id": value.id.val,
        "claim": enc_ref(value.claim),
        "witness": enc_witness(value.witness),
    }


def dec_correction(value: object) -> M.Correction:
    v = obj(value, "id kind target replacement recorded_at")
    return M.Correction(
        CorrectionId(text(v["id"])),
        M.CorrectionKind(text(v["kind"])),
        dec_ref(v["target"]),
        None if v["replacement"] is None else dec_ref(v["replacement"]),
        nat(v["recorded_at"]),
    )


def enc_correction(value: M.Correction) -> dict[str, object]:
    return {
        "id": value.id.val,
        "kind": value.kind.value,
        "target": enc_ref(value.target),
        "replacement": None if value.replacement is None else enc_ref(value.replacement),
        "recorded_at": value.recorded_at,
    }


def dec_ttl(value: object) -> M.Ttl:
    if value is None:
        return M.TTL_MISSING
    if is_object(value):
        record = obj(value, "tag")
        if text(record["tag"]) != "noExpiry":
            raise ValueError("invalid_request")
        return M.TTL_NO_EXPIRY
    return M.ttl_expire_after(nat(value))


def enc_ttl(value: M.Ttl) -> object:
    if value.tag is M.TtlTag.NO_EXPIRY:
        return {"tag": "noExpiry"}
    if value.tag is M.TtlTag.MISSING:
        return None
    return value.secs


def dec_policy(value: object) -> M.Policy:
    v = obj(value, "id require_fresh require_validation require_uncontested ttl authorized_actors")
    actors = items(v["authorized_actors"], lambda actor: ActorId(nonempty(actor)))
    if len(set(actors)) != len(actors):
        raise ValueError("invalid_request")
    return M.Policy(
        PolicyId(text(v["id"])),
        boolean(v["require_fresh"]),
        boolean(v["require_validation"]),
        boolean(v["require_uncontested"]),
        dec_ttl(v["ttl"]),
        actors,
    )


def enc_policy(value: M.Policy) -> dict[str, object]:
    return {
        "id": value.id.val,
        "require_fresh": value.require_fresh,
        "require_validation": value.require_validation,
        "require_uncontested": value.require_uncontested,
        "ttl": enc_ttl(value.ttl),
        "authorized_actors": [actor.val for actor in value.authorized_actors],
    }


def dec_source_selection(value: object) -> M.SourceSelection:
    v = obj(value, "source revision content")
    return M.SourceSelection(
        SourceId(nonempty(v["source"])),
        SourceRevision(nonempty(v["revision"])),
        ContentId(nonempty(v["content"])),
    )


def enc_source_selection(value: M.SourceSelection) -> dict[str, object]:
    return {
        "source": value.source.val,
        "revision": value.revision.val,
        "content": value.content.val,
    }


def dec_context(value: object) -> M.Context:
    v = obj(
        value, "snapshot semantic_version ruleset checker policy now target intended_use sources"
    )
    result = M.Context(
        SnapshotId(text(v["snapshot"])),
        text(v["semantic_version"]),
        RuleVersion(text(v["ruleset"])),
        CheckerId(text(v["checker"])),
        dec_policy(v["policy"]),
        nat(v["now"]),
        dec_scope(v["target"]),
        nonempty(v["intended_use"]),
        items(v["sources"], dec_source_selection),
    )
    if not context_wf(result):
        raise ValueError("invalid_request")
    return result


def enc_context(value: M.Context) -> dict[str, object]:
    return {
        "snapshot": value.snapshot.val,
        "semantic_version": value.semantic_version,
        "ruleset": value.ruleset.val,
        "checker": value.checker.val,
        "policy": enc_policy(value.policy),
        "now": value.now,
        "target": enc_scope(value.target),
        "intended_use": value.intended_use,
        "sources": [enc_source_selection(source) for source in value.sources],
    }


def dec_dependency(value: object) -> M.Dependency:
    v = obj(value)
    tag = text(v.get("tag"))
    if tag == "corrections":
        obj(v, "tag target events")
        return M.CorrectionsDependency(dec_ref(v["target"]), items(v["events"], dec_correction))
    obj(v, "tag value")
    if tag == "observation":
        return M.ObservationDependency(dec_observation(v["value"]))
    if tag == "claim":
        return M.ClaimDependency(dec_claim(v["value"]))
    if tag == "attestation":
        return M.AttestationDependency(dec_attestation(v["value"]))
    if tag == "enumeration":
        return M.EnumerationDependency(dec_enumeration(v["value"]))
    if tag == "context":
        context = dec_context(v["value"])
        if context.now != 0:
            raise ValueError("invalid_request")
        return M.ContextDependency(context)
    raise ValueError("invalid_request")


def enc_dependency(value: M.Dependency) -> dict[str, object]:
    if isinstance(value, M.ObservationDependency):
        return {"tag": "observation", "value": enc_observation(value.value)}
    if isinstance(value, M.ClaimDependency):
        return {"tag": "claim", "value": enc_claim(value.value)}
    if isinstance(value, M.AttestationDependency):
        return {"tag": "attestation", "value": enc_attestation(value.value)}
    if isinstance(value, M.EnumerationDependency):
        return {"tag": "enumeration", "value": enc_enumeration(value.value)}
    if isinstance(value, M.CorrectionsDependency):
        return {
            "tag": "corrections",
            "target": enc_ref(value.target),
            "events": [enc_correction(c) for c in value.events],
        }
    return {"tag": "context", "value": enc_context(value.value)}


def dec_receipt(value: object) -> M.Receipt:
    v = obj(value, "id claim context witness dependencies result expires_at")
    return M.Receipt(
        ReceiptId(text(v["id"])),
        dec_ref(v["claim"]),
        dec_context(v["context"]),
        dec_witness(v["witness"]),
        items(v["dependencies"], dec_dependency),
        M.ReceiptResult(text(v["result"])),
        nat(v["expires_at"]),
    )


def enc_receipt(value: M.Receipt) -> dict[str, object]:
    return {
        "id": value.id.val,
        "claim": enc_ref(value.claim),
        "context": enc_context(value.context),
        "witness": enc_witness(value.witness),
        "dependencies": [enc_dependency(o) for o in value.dependencies],
        "result": value.result.value,
        "expires_at": value.expires_at,
    }


def dec_kb(value: object) -> M.KB:
    v = obj(
        value,
        "snapshot observations claims attestations enumerations derivations corrections receipts",
    )
    result = M.KB(
        SnapshotId(text(v["snapshot"])),
        items(v["observations"], dec_observation),
        items(v["claims"], dec_claim),
        items(v["attestations"], dec_attestation),
        items(v["enumerations"], dec_enumeration),
        items(v["derivations"], dec_derivation),
        items(v["corrections"], dec_correction),
        items(v["receipts"], dec_receipt),
    )
    if not well_formed(result):
        raise ValueError("invalid_request")
    return result


def enc_kb(value: M.KB) -> dict[str, object]:
    return {
        "snapshot": value.snapshot.val,
        "observations": [enc_observation(o) for o in value.observations],
        "claims": [enc_claim(c) for c in value.claims],
        "attestations": [enc_attestation(a) for a in value.attestations],
        "enumerations": [enc_enumeration(e) for e in value.enumerations],
        "derivations": [enc_derivation(d) for d in value.derivations],
        "corrections": [enc_correction(c) for c in value.corrections],
        "receipts": [enc_receipt(r) for r in value.receipts],
    }


def dec_authority(value: object) -> M.Authority:
    v = obj(value, "actor target intended_use policy statement approved approvals context")
    return M.Authority(
        ActorId(nonempty(v["actor"])),
        dec_ref(v["target"]),
        nonempty(v["intended_use"]),
        PolicyId(text(v["policy"])),
        dec_statement(v["statement"]),
        dec_kb(v["approved"]),
        items(v["approvals"], dec_claim),
        dec_context(v["context"]),
    )


def enc_authority(value: M.Authority) -> dict[str, object]:
    return {
        "actor": value.actor.val,
        "target": enc_ref(value.target),
        "intended_use": value.intended_use,
        "policy": value.policy.val,
        "statement": enc_statement(value.statement),
        "approved": enc_kb(value.approved),
        "approvals": [enc_claim(c) for c in value.approvals],
        "context": enc_context(value.context),
    }


def dec_plan(value: object) -> M.Plan:
    v = obj(value, "id expected_snapshot candidate authority claim witness")
    return M.Plan(
        OperationId(text(v["id"])),
        SnapshotId(text(v["expected_snapshot"])),
        dec_kb(v["candidate"]),
        dec_authority(v["authority"]),
        dec_ref(v["claim"]),
        dec_witness(v["witness"]),
    )


def enc_plan(value: M.Plan) -> dict[str, object]:
    return {
        "id": value.id.val,
        "expected_snapshot": value.expected_snapshot.val,
        "candidate": enc_kb(value.candidate),
        "authority": enc_authority(value.authority),
        "claim": enc_ref(value.claim),
        "witness": enc_witness(value.witness),
    }


def dec_journal_entry(value: object) -> M.JournalEntry:
    return M.JournalEntry(dec_plan(obj(value, "plan")["plan"]))


def enc_journal_entry(value: M.JournalEntry) -> dict[str, object]:
    return {"plan": enc_plan(value.plan)}


def enc_assessment(value: M.Assessment) -> dict[str, object]:
    return {
        "support": value.support.value,
        "applicable": value.applicable,
        "freshness": value.freshness.value,
        "validated": value.validated,
        "contested": value.contested,
        "available": value.available,
        "usable": value.usable,
    }


def enc_checked(value: M.Checked | None) -> object:
    return (
        None
        if value is None
        else {
            "statement": enc_statement(value.statement),
            "dependencies": [enc_dependency(o) for o in value.dependencies],
        }
    )


def dec_proposal(value: object) -> M.Proposal:
    v = obj(value, "id revision target status actor executor acceptor gates")
    return M.Proposal(
        ProposalId(text(v["id"])),
        ClaimRevision(text(v["revision"])),
        dec_ref(v["target"]),
        M.ProposalStatus(text(v["status"])),
        optional_identity(v["actor"], ActorId),
        optional_identity(v["executor"], ActorId),
        optional_identity(v["acceptor"], ActorId),
        items(v["gates"], lambda item: ReceiptId(text(item))),
    )


def enc_proposal(value: M.Proposal) -> dict[str, object]:
    return {
        "id": value.id.val,
        "revision": value.revision.val,
        "target": enc_ref(value.target),
        "status": value.status.value,
        "actor": enc_optional_identity(value.actor),
        "executor": enc_optional_identity(value.executor),
        "acceptor": enc_optional_identity(value.acceptor),
        "gates": [gate.val for gate in value.gates],
    }


def dec_hypothesis(value: object) -> M.Hypothesis:
    v = obj(value, "text status")
    return M.Hypothesis(text(v["text"]), M.HypothesisStatus(text(v["status"])))


def dec_investigation(value: object) -> M.Investigation:
    v = obj(value, "checked_against scope_and_limits hypotheses")
    return M.Investigation(
        text(v["checked_against"]),
        text(v["scope_and_limits"]),
        items(v["hypotheses"], dec_hypothesis),
    )


def enc_investigation(value: M.Investigation) -> dict[str, object]:
    return {
        "checked_against": value.checked_against,
        "scope_and_limits": value.scope_and_limits,
        "hypotheses": [
            {"text": hypothesis.text, "status": hypothesis.status.value}
            for hypothesis in value.hypotheses
        ],
    }


def dec_authored_gate_definition(value: object) -> M.AuthoredGateDefinition:
    v = obj(value, "id claim check when by checker")
    return M.AuthoredGateDefinition(
        GateId(text(v["id"])),
        text(v["claim"]),
        text(v["check"]),
        M.GateWhen(text(v["when"])),
        optional_identity(v["by"], ActorId),
        optional_identity(v["checker"], CheckerId),
    )


def enc_authored_gate_definition(value: M.AuthoredGateDefinition) -> dict[str, object]:
    return {
        "id": value.id.val,
        "claim": value.claim,
        "check": value.check,
        "when": value.when.value,
        "by": enc_optional_identity(value.by),
        "checker": enc_optional_identity(value.checker),
    }


def dec_authored_gate_result(value: object) -> M.AuthoredGateResult:
    v = obj(
        value,
        "definition target_revision checker result observed_at expires_at proposal_revision environment scope evidence_refs actor",
    )
    return M.AuthoredGateResult(
        dec_authored_gate_definition(v["definition"]),
        optional_identity(v["target_revision"], TargetRevision),
        optional_identity(v["checker"], CheckerId),
        M.GateOutcome(text(v["result"])),
        nat(v["observed_at"]),
        nat(v["expires_at"]),
        optional_identity(v["proposal_revision"], ProposalMaterialRevision),
        text(v["environment"]),
        text(v["scope"]),
        items(v["evidence_refs"], text),
        optional_identity(v["actor"], ActorId),
    )


def enc_authored_gate_result(value: M.AuthoredGateResult) -> dict[str, object]:
    return {
        "definition": enc_authored_gate_definition(value.definition),
        "target_revision": enc_optional_identity(value.target_revision),
        "checker": enc_optional_identity(value.checker),
        "result": value.result.value,
        "observed_at": value.observed_at,
        "expires_at": value.expires_at,
        "proposal_revision": enc_optional_identity(value.proposal_revision),
        "environment": value.environment,
        "scope": value.scope,
        "evidence_refs": list(value.evidence_refs),
        "actor": enc_optional_identity(value.actor),
    }


def dec_authored_replacement(value: object) -> M.AuthoredReplacement:
    v = obj(value, "id superseded_by")
    return M.AuthoredReplacement(
        ProposalId(text(v["id"])),
        None if v["superseded_by"] is None else ProposalId(text(v["superseded_by"])),
    )


def dec_authored_landed(value: object) -> M.AuthoredLanded:
    v = obj(value, "reference target_revision")
    return M.AuthoredLanded(text(v["reference"]), TargetRevision(text(v["target_revision"])))


def dec_authored_proposal(value: object) -> M.AuthoredProposal:
    v = obj(
        value,
        "status profile research_present alternatives_count target_revision gate_definitions gate_results actor acceptor executor verifier landed_refs regression_note id superseded_by proposals accepted_revision proposal_revision environment scope resolved_landed",
    )
    definitions = items(v["gate_definitions"], dec_authored_gate_definition)
    if len({definition.id for definition in definitions}) != len(definitions):
        raise ValueError("invalid_request")
    return M.AuthoredProposal(
        M.AuthoredStatus(text(v["status"])),
        M.AuthoredProfile(text(v["profile"])),
        boolean(v["research_present"]),
        nat(v["alternatives_count"]),
        optional_identity(v["target_revision"], TargetRevision),
        definitions,
        items(v["gate_results"], dec_authored_gate_result),
        optional_identity(v["actor"], ActorId),
        optional_identity(v["acceptor"], ActorId),
        optional_identity(v["executor"], ActorId),
        optional_identity(v["verifier"], ActorId),
        items(v["landed_refs"], text),
        text(v["regression_note"]),
        ProposalId(text(v["id"])),
        None if v["superseded_by"] is None else ProposalId(text(v["superseded_by"])),
        items(v["proposals"], dec_authored_replacement),
        optional_identity(v["accepted_revision"], ProposalMaterialRevision),
        optional_identity(v["proposal_revision"], ProposalMaterialRevision),
        text(v["environment"]),
        text(v["scope"]),
        items(v["resolved_landed"], dec_authored_landed),
    )


def enc_authored_proposal(value: M.AuthoredProposal) -> dict[str, object]:
    return {
        "status": value.status.value,
        "profile": value.profile.value,
        "research_present": value.research_present,
        "alternatives_count": value.alternatives_count,
        "target_revision": enc_optional_identity(value.target_revision),
        "gate_definitions": [enc_authored_gate_definition(d) for d in value.gate_definitions],
        "gate_results": [enc_authored_gate_result(r) for r in value.gate_results],
        "actor": enc_optional_identity(value.actor),
        "acceptor": enc_optional_identity(value.acceptor),
        "executor": enc_optional_identity(value.executor),
        "verifier": enc_optional_identity(value.verifier),
        "landed_refs": list(value.landed_refs),
        "regression_note": value.regression_note,
        "id": value.id.val,
        "superseded_by": None if value.superseded_by is None else value.superseded_by.val,
        "proposals": [
            {
                "id": row.id.val,
                "superseded_by": None if row.superseded_by is None else row.superseded_by.val,
            }
            for row in value.proposals
        ],
        "accepted_revision": enc_optional_identity(value.accepted_revision),
        "proposal_revision": enc_optional_identity(value.proposal_revision),
        "environment": value.environment,
        "scope": value.scope,
        "resolved_landed": [
            {"reference": resolution.reference, "target_revision": resolution.target_revision.val}
            for resolution in value.resolved_landed
        ],
    }


def dec_selection_state(value: object) -> M.SelectionState:
    v = obj(value, "kb selected")
    state = M.SelectionState(dec_kb(v["kb"]), items(v["selected"], dec_ref))
    if len(set(state.selected)) != len(state.selected) or any(
        M.find_claim(state.kb, ref) is None for ref in state.selected
    ):
        raise ValueError("invalid_request")
    return state


def enc_selection_state(value: M.SelectionState) -> dict[str, object]:
    return {"kb": enc_kb(value.kb), "selected": [enc_ref(ref) for ref in value.selected]}


def dec_selection_plan(value: object) -> M.SelectionPlan:
    v = obj(
        value,
        "id expected_snapshot target_snapshot new_snapshot selected actor policy intended_use context",
    )
    selected = items(v["selected"], dec_ref)
    if len(set(selected)) != len(selected):
        raise ValueError("invalid_request")
    return M.SelectionPlan(
        OperationId(text(v["id"])),
        SnapshotId(text(v["expected_snapshot"])),
        SnapshotId(text(v["target_snapshot"])),
        SnapshotId(text(v["new_snapshot"])),
        selected,
        optional_identity(v["actor"], ActorId),
        PolicyId(text(v["policy"])),
        text(v["intended_use"]),
        dec_context(v["context"]),
    )


def enc_selection_plan(value: M.SelectionPlan) -> dict[str, object]:
    return {
        "id": value.id.val,
        "expected_snapshot": value.expected_snapshot.val,
        "target_snapshot": value.target_snapshot.val,
        "new_snapshot": value.new_snapshot.val,
        "selected": [enc_ref(ref) for ref in value.selected],
        "actor": enc_optional_identity(value.actor),
        "policy": value.policy.val,
        "intended_use": value.intended_use,
        "context": enc_context(value.context),
    }


def dec_selection_journal_entry(value: object) -> M.SelectionJournalEntry:
    return M.SelectionJournalEntry(dec_selection_plan(obj(value, "plan")["plan"]))


def enc_selection_journal_entry(value: M.SelectionJournalEntry) -> dict[str, object]:
    return {"plan": enc_selection_plan(value.plan)}


def enc_selection_result(value: M.SelectionResult) -> dict[str, object]:
    return {
        "state": enc_selection_state(value.state),
        "journal": [enc_selection_journal_entry(entry) for entry in value.journal],
        "outcome": value.outcome.value,
    }


def _retrieve_result(
    kb: M.KB, context: M.Context, claims: tuple[M.Claim, ...], offset: int, limit: int
) -> dict[str, object]:
    if not context_matches(kb, context):
        raise ValueError("invalid_request")
    relevant = tuple(claim for claim in claims if M.narrower(context.target, claim.statement.scope))
    selected = relevant[offset : offset + limit]
    omitted = max(0, len(relevant) - offset - len(selected))
    return {
        "snapshot": kb.snapshot.val,
        "records": [
            {
                "claim": enc_claim(claim),
                "assessment": enc_assessment(assess(kb, context, claim.ref)),
            }
            for claim in selected
        ],
        "omitted": omitted,
        "complete": omitted == 0,
        "next_offset": None if omitted == 0 else offset + len(selected),
    }


_BASE = "schema_version semantic_version id op"


def handle(
    request: dict[str, object],
    trusted_approvals: tuple[M.VerifiedApproval, ...] = (),
    trusted_selections: tuple[M.VerifiedSelectionApproval, ...] = (),
    retained: tuple[M.KB, ...] = (),
) -> object:
    if (
        type(request["schema_version"]) is not int
        or request["schema_version"] != M.SCHEMA_VERSION
        or request["semantic_version"] != M.SEMANTIC_VERSION
    ):
        raise ValueError("invalid_request")
    nonempty(request["id"])
    operation = text(request["op"])
    if operation in ("select", "retrieve_selected"):
        obj(
            request,
            _BASE
            + (
                " state context journal plan"
                if operation == "select"
                else " state context offset limit"
            ),
        )
        state, context = dec_selection_state(request["state"]), dec_context(request["context"])
        if operation == "retrieve_selected":
            claims = tuple(claim for claim in state.kb.claims if claim.ref in state.selected)
            return _retrieve_result(
                state.kb, context, claims, nat(request["offset"]), nat(request["limit"])
            )
        journal = items(request["journal"], dec_selection_journal_entry)
        if len({entry.plan.id for entry in journal}) != len(journal):
            raise ValueError("invalid_request")
        result = apply_selection(
            state,
            context,
            journal,
            dec_selection_plan(request["plan"]),
            trusted_approvals=trusted_selections,
            retained=retained,
        )
        return enc_selection_result(result)
    if operation == "semantic_version":
        obj(request, _BASE)
        return M.SEMANTIC_VERSION
    if operation == "fresh":
        obj(request, _BASE + " now observed_at ttl")
        ttl = dec_ttl(request["ttl"])
        return assess_fresh(ttl, nat(request["observed_at"]), nat(request["now"])).value
    if operation == "validate":
        obj(request, _BASE + " kb")
        dec_kb(request["kb"])
        return True
    if operation == "conclude":
        obj(request, _BASE + " investigation")
        return conclude(dec_investigation(request["investigation"]))
    if operation in ("authored_transition", "authored_candidate_valid"):
        obj(request, _BASE + " proposal target_status now")
        decision = (
            authored_transition if operation == "authored_transition" else authored_candidate_valid
        )
        return decision(
            dec_authored_proposal(request["proposal"]),
            M.AuthoredStatus(text(request["target_status"])),
            nat(request["now"]),
        )
    fields = {
        "check": "witness",
        "supported": "claim polarity",
        "assess": "claim",
        "usable": "claim",
        "reuse": "claim receipt",
        "retrieve": "offset limit",
        "admit": "plan",
        "sequence": "journal plans",
        "transition": "proposal target_status",
    }
    if operation not in fields:
        raise ValueError("invalid_request")
    obj(request, _BASE + " kb context " + fields[operation])
    kb, context = dec_kb(request["kb"]), dec_context(request["context"])
    if operation == "transition":
        return transition(
            kb,
            context,
            dec_proposal(request["proposal"]),
            M.ProposalStatus(text(request["target_status"])),
        )
    if operation == "check":
        return enc_checked(check(kb, context, dec_witness(request["witness"])))
    if operation == "supported":
        return supported(
            kb, context, dec_ref(request["claim"]), M.Polarity(text(request["polarity"]))
        )
    if operation in ("assess", "usable"):
        result = assess(kb, context, dec_ref(request["claim"]))
        return result.usable if operation == "usable" else enc_assessment(result)
    if operation == "reuse":
        return reusable(kb, context, dec_ref(request["claim"]), dec_receipt(request["receipt"]))
    if operation == "retrieve":
        return _retrieve_result(
            kb, context, kb.claims, nat(request["offset"]), nat(request["limit"])
        )
    if operation == "admit":
        applied = apply_plan(
            kb, context, (), dec_plan(request["plan"]), trusted_approvals=trusted_approvals
        )
        return {
            "kb": enc_kb(applied.kb),
            "journal": [enc_journal_entry(e) for e in applied.journal],
            "outcome": applied.outcome.value,
        }
    if not context_matches(kb, context):
        raise ValueError("invalid_request")
    journal = items(request["journal"], dec_journal_entry)
    if len({e.plan.id for e in journal}) != len(journal):
        raise ValueError("invalid_request")
    outcomes: list[str] = []
    for plan in items(request["plans"], dec_plan):
        applied = apply_plan(
            kb,
            replace(context, snapshot=kb.snapshot),
            journal,
            plan,
            trusted_approvals=trusted_approvals,
        )
        kb, journal = applied.kb, applied.journal
        outcomes.append(applied.outcome.value)
    return {
        "kb": enc_kb(kb),
        "journal": [enc_journal_entry(e) for e in journal],
        "outcomes": outcomes,
    }


def evaluate_request(
    request: dict[str, object],
    *,
    trusted_approvals: tuple[M.VerifiedApproval, ...] = (),
    trusted_selections: tuple[M.VerifiedSelectionApproval, ...] = (),
    retained: tuple[M.KB, ...] = (),
) -> dict[str, object]:
    ident = request.get("id", "")
    try:
        if request.get("schema_version") == 3:
            if trusted_approvals or trusted_selections or retained:
                raise ValueError("v2 capabilities cannot authorize workflow schema 3")
            from kctx.semantics.workflow_reference import evaluate_request as evaluate_workflow

            return evaluate_workflow(request)
        result = handle(request, trusted_approvals, trusted_selections, retained)
        return {"id": ident, "ok": True, "result": result}
    except (ValueError, KeyError, TypeError, RecursionError, KctxError):
        return {
            "id": ident if isinstance(ident, str) and _unicode_scalars(ident) else "",
            "ok": False,
            "error": "invalid_request",
        }


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("invalid_request")
        result[key] = value
    return result


def _validate_unicode(value: object) -> None:
    """Lean strings contain Unicode scalar values, not isolated UTF-16 surrogates."""
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, str):
            text(current)
        elif is_object(current):
            for key, item in current.items():
                text(key)
                pending.append(item)
        elif is_array(current):
            pending.extend(current)


def loads_request(raw: str) -> dict[str, object]:
    value: object = json.loads(raw, object_pairs_hook=_unique_pairs)
    _validate_unicode(value)
    return obj(value)


def evaluate_json(raw: str) -> str:
    try:
        result = evaluate_request(loads_request(raw))
    except (ValueError, RecursionError):
        result = {"id": "", "ok": False, "error": "invalid_request"}
    return json.dumps(result, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
