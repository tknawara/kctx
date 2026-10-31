"""Construction policies for non-code citations and live proposal records."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from kctx.citations.models import MadeCitation
from kctx.citations.records import load_proposal_record
from kctx.citations.syntax import format_cite
from kctx.citations.time import iso_now_minute
from kctx.config import Config
from kctx.domain.ids import ProposalId
from kctx.errors import KctxError


@dataclass(frozen=True, slots=True)
class KindSpec:
    required: tuple[str | tuple[str, ...], ...]
    q_required: bool
    default_ttl: str


QUERY_ALIASES: Mapping[str, str] = MappingProxyType(
    {"metric": "guts", "log": "humio", "data": "sql"}
)
KIND_SPECS: Mapping[str, KindSpec] = MappingProxyType(
    {
        "commit": KindSpec(("repo", "rev"), False, "none"),
        "pr": KindSpec(("repo", "n"), True, "3d"),
        "ticket": KindSpec(("id",), True, "3d"),
        "breg": KindSpec(("name", "env"), True, "1d"),
        "deploy": KindSpec((("asset", "service"), "env"), True, "1d"),
        "query": KindSpec(("sys", "q"), True, "none"),
        "doc": KindSpec(("url", "section"), True, "30d"),
        "web": KindSpec(("url",), True, "30d"),
        "usr": KindSpec(("date", "where"), False, "none"),
        "ev": KindSpec(("id",), False, "none"),
        "gate": KindSpec(("proposal", "gate", "outcome", "rev"), False, "none"),
        "record": KindSpec(("path", "state"), False, "none"),
    }
)
SENS_VALUES = frozenset({"public", "internal", "restricted"})
GATE_OUTCOMES = frozenset({"pass", "fail", "unk"})
PROPOSAL_TERMINAL_STATES = frozenset({"verified", "rejected", "superseded"})
PROPOSAL_FIELD_ORDER = ("kind", "id", "state", "seen", "ttl", "sens", "redact", "note")


def validate_required(kind: str, fields: Mapping[str, str]) -> None:
    spec = KIND_SPECS[kind]
    for requirement in spec.required:
        if isinstance(requirement, tuple):
            if not any(fields.get(key) for key in requirement):
                raise KctxError(
                    "incomplete", f"kind={kind} requires one of {'/'.join(requirement)}="
                )
        elif not fields.get(requirement):
            raise KctxError("incomplete", f"kind={kind} requires {requirement}=")
    if spec.q_required and not fields.get("q"):
        raise KctxError("incomplete", f"kind={kind} requires q=")


def _order_for_kind(kind: str) -> list[str]:
    order = ["kind"]
    for requirement in KIND_SPECS[kind].required:
        order.extend(requirement if isinstance(requirement, tuple) else (requirement,))
    order.extend(
        (
            "q",
            "sys",
            "n",
            "env",
            "name",
            "asset",
            "service",
            "state",
            "value",
            "version",
            "rows",
            "ev",
            "result",
            "window",
            "quote",
            "section",
            "modified",
            "where",
            "who",
            "seen",
            "ttl",
            "sens",
            "redact",
            "note",
        )
    )
    return list(dict.fromkeys(order))


def make_other(kind: str, fields: Mapping[str, str]) -> MadeCitation:
    values = dict(fields)
    canonical = kind
    if kind in QUERY_ALIASES:
        values.setdefault("sys", QUERY_ALIASES[kind])
        canonical = "query"
    if canonical not in KIND_SPECS:
        expected = sorted(set(KIND_SPECS) | set(QUERY_ALIASES))
        raise KctxError("malformed", f"unknown kind {kind!r}; expected one of {expected}")
    values["kind"] = canonical
    validate_required(canonical, values)
    if values.get("sens") and values["sens"] not in SENS_VALUES:
        raise KctxError("malformed", f"sens={values['sens']!r} not one of {sorted(SENS_VALUES)}")
    if canonical == "gate" and values.get("outcome") not in GATE_OUTCOMES:
        raise KctxError(
            "malformed", f"outcome={values.get('outcome')!r} not one of {sorted(GATE_OUTCOMES)}"
        )
    values.setdefault("ttl", KIND_SPECS[canonical].default_ttl)
    values.setdefault("seen", iso_now_minute())
    return MadeCitation(format_cite(values, _order_for_kind(canonical)), values)


def make_proposal(
    id_: ProposalId | str,
    ttl: str | None = None,
    *,
    config: Config | None = None,
) -> MadeCitation:
    identifier = id_ if isinstance(id_, ProposalId) else ProposalId(id_)
    record = load_proposal_record(identifier, config=config)
    if record is None:
        raise KctxError(
            "not-found",
            f"proposal {str(identifier)!r} not found (looked for "
            f"proposals/{identifier}.md and proposals/{identifier}/proposal.md under the projects root)",
        )
    state = record.status or "unk"
    fields = {
        "kind": "proposal",
        "id": str(identifier),
        "state": state,
        "seen": iso_now_minute(),
        "ttl": ttl or ("none" if state in PROPOSAL_TERMINAL_STATES else "7d"),
    }
    return MadeCitation(format_cite(fields, PROPOSAL_FIELD_ORDER), fields)
