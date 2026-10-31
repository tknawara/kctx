"""Strict persisted acceptance-gate result boundary, including exact bindings."""

from kctx.domain.ids import GateId, ProposalMaterialRevision, TargetRevision
from kctx.domain.json import fields, integer, text
from kctx.domain.proposals import GateDefinition, GateResult
from kctx.domain.vocabulary import GateOutcome, GateWhen
from kctx.errors import KctxError


def decode_gate_definition(raw: object) -> GateDefinition:
    data = fields(
        raw, required={"id", "when", "claim", "check", "by"}, optional={"checker"}, versioned=False
    )
    try:
        return GateDefinition(
            GateId(text(data["id"], "id")),
            GateWhen(text(data["when"], "when")),
            text(data["claim"], "claim"),
            text(data["check"], "check"),
            text(data["by"], "by"),
            text(data.get("checker", ""), "checker"),
        )
    except ValueError as exc:
        raise KctxError("malformed", f"invalid gate definition: {exc}") from exc


def decode_gate_result(raw: object) -> GateResult:
    data = fields(
        raw,
        required={"gate", "outcome", "evidence", "at"},
        optional={
            "by",
            "rev",
            "target_revision",
            "checker",
            "observed_at",
            "expires_at",
            "definition",
            "proposal_revision",
            "environment",
            "scope",
        },
        versioned=False,
    )

    def optional(key: str) -> str | None:
        return text(data[key], key) if key in data else None

    def timestamp(key: str) -> int | None:
        if key not in data:
            return None
        value = integer(data[key], key)
        if value < 0:
            raise KctxError("malformed", f"gate result {key!r} must be nonnegative")
        return value

    try:
        result = GateResult(
            GateId(text(data["gate"], "gate")),
            GateOutcome(text(data["outcome"], "outcome")),
            text(data["evidence"], "evidence"),
            text(data["at"], "at"),
            optional("by"),
            optional("rev"),
            TargetRevision(text(data["target_revision"], "target_revision"))
            if "target_revision" in data
            else None,
            optional("checker"),
            timestamp("observed_at"),
            timestamp("expires_at"),
            decode_gate_definition(data["definition"]) if "definition" in data else None,
            ProposalMaterialRevision(text(data["proposal_revision"], "proposal_revision"))
            if "proposal_revision" in data
            else None,
            optional("environment"),
            optional("scope"),
        )
    except ValueError as exc:
        raise KctxError("malformed", f"invalid gate result: {exc}") from exc
    binding = (
        result.target_revision,
        result.checker,
        result.observed_at,
        result.expires_at,
        result.definition,
        result.proposal_revision,
        result.environment,
        result.scope,
    )
    if any(value is not None for value in binding) and not all(
        value is not None for value in binding
    ):
        raise KctxError(
            "malformed",
            "gate result binding must include definition, proposal/target revisions, environment, scope, checker and times",
        )
    if result.definition is not None and result.gate != result.definition.id:
        raise KctxError("malformed", "gate result identity disagrees with its retained definition")
    if result.definition is not None:
        if not all(
            value and value.strip()
            for value in (
                result.evidence,
                result.by,
                result.rev,
                result.target_revision.val if result.target_revision is not None else None,
                result.checker,
                result.proposal_revision.val if result.proposal_revision is not None else None,
                result.environment,
                result.scope,
            )
        ):
            raise KctxError(
                "malformed",
                "bound gate result requires evidence, actor, definition revision, target revision and checker",
            )
        if (
            result.observed_at is not None
            and result.expires_at is not None
            and result.expires_at < result.observed_at
        ):
            raise KctxError("malformed", "gate result expires before it was observed")
    return result


def encode_gate_result(result: GateResult) -> dict[str, object]:
    wire: dict[str, object] = {
        "gate": result.gate.val,
        "outcome": result.outcome.value,
        "evidence": result.evidence,
        "at": result.at,
    }
    for key, value in (
        ("by", result.by),
        ("rev", result.rev),
        (
            "target_revision",
            result.target_revision.val if result.target_revision is not None else None,
        ),
        ("checker", result.checker),
        ("observed_at", result.observed_at),
        ("expires_at", result.expires_at),
        (
            "proposal_revision",
            result.proposal_revision.val if result.proposal_revision is not None else None,
        ),
        ("environment", result.environment),
        ("scope", result.scope),
    ):
        if value is not None:
            wire[key] = value
    if result.definition is not None:
        wire["definition"] = encode_gate_definition(result.definition)
    return wire


def encode_gate_definition(gate: GateDefinition) -> dict[str, str]:
    wire = {"id": gate.id.val, "when": gate.when.value}
    for key, value in (
        ("claim", gate.claim),
        ("check", gate.check),
        ("by", gate.by),
        ("checker", gate.checker),
    ):
        if value is not None:
            wire[key] = value
    return wire
