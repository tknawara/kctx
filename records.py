"""Typed record shapes for the knowledge workspace.

Every persisted JSON record carries schema_version so a future format change
can be detected rather than silently misread.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from errors import KctxError

SCHEMA_VERSION = 1

ASSET_KINDS = {
    "repo",
    "service",
    "package",
    "api",
    "schema",
    "dashboard",
    "alert",
    "doc",
    "runbook",
    "pipeline",
    "deployment",
    "environment",
    "store",
    "other",
}
LIFECYCLES = {"active", "deprecated", "retired"}

REL_TYPES = {
    "produces",
    "consumes",
    "implements",
    "defines-contract-for",
    "documents",
    "depends-on",
    "monitors",
    "alerts-on",
    "deploys",
    "owned-by",
}
REL_STATUSES = {"explicit", "inferred", "confirmed", "disputed", "retired"}

OBS_SYSTEMS = {
    "git",
    "bbgithub",
    "grafana",
    "humio",
    "metrics",
    "deployment",
    "doc",
    "other",
}
OBS_ROLES = {"contract", "code", "runtime", "doc", "deployment", "note"}
OBS_STATUSES = {
    "ok",
    "error",
    "timeout",
    "denied",
    "not-found",
    "no-data",
    "partial",
    "truncated",
}

# Outcomes a human may set via `kctx cover`.
COVERAGE_OUTCOMES = {
    "supported",
    "violated",
    "inconclusive",
    "unavailable",
    "not-examined",
    "not-applicable",
}
# Outcomes that may additionally appear once `kctx check` has run, marking an
# entry whose cited evidence moved since it was recorded.
COVERAGE_RUNTIME_OUTCOMES = COVERAGE_OUTCOMES | {"needs-recheck"}

# "steward" and "skill" are legacy kinds (origin used to be conflated with
# kind); new filings use "config" for anything landing in dotfiles or this
# repo's kb tooling. "decision" and "other" are unchanged.
PROPOSAL_KINDS = {"steward", "skill", "config", "decision", "other"}
PROPOSAL_TYPES = {
    "memory",
    "skill-refinement",
    "new-skill",
    "agent",
    "settings",
    "module",
    "kb-tooling",
}
PROPOSAL_STATUSES = {
    "draft",
    "proposed",
    "accepted",
    "rejected",
    "landing",
    "applied",
    "verified",
    "regressed",
    "superseded",
    "deferred",
}
# Statuses that require --by: the three original "decided" statuses, plus
# landing (where --by records the executor's identity, so two sessions don't
# land the same proposal at once) -- see proposals.PROPOSAL_TRANSITIONS.
PROPOSAL_DECIDED_STATUSES = {"accepted", "rejected", "applied", "landing"}

# proposals.add()'s origin kwarg (required for new filings) and the
# one-time Context-section backfill on proposals filed before origin
# existed. "unk" covers a backfilled proposal whose Context doesn't say.
PROPOSAL_ORIGINS = {
    "steward",
    "user-request",
    "suggest-skills",
    "review-finding",
    "consolidation",
    "other",
    "unk",
}

# proposals.set_status()'s lifecycle graph (evolve skill, section 1e).
# "superseded" is reachable from any status and isn't listed as a value here.
PROPOSAL_TRANSITIONS = {
    "draft": {"proposed"},
    "proposed": {"draft", "accepted", "rejected"},
    "accepted": {"landing", "deferred"},
    "landing": {"applied"},
    "applied": {"verified", "regressed"},
    "rejected": set(),
    "deferred": set(),
    "verified": set(),
    "regressed": set(),
    "superseded": set(),
}

GATE_OUTCOMES = {"pass", "fail", "unk"}
GATE_WHENS = {"land", "deploy", "use"}

RUN_MODES = {"advice", "review", "authoring"}

# Shared with <project>/inventory.md's state tokens (projects CLAUDE.md).
KTLO_STATUSES = {"todo", "investigating", "in-progress", "blocked", "done", "n/a"}

# investigations/<YYYY>/<YYYY-MM-DD>-<slug>/README.md -- the ops-knowledge-layer
# proposal's intake trigger, lifecycle status, and per-hypothesis status.
INVESTIGATION_TRIGGERS = {"alert", "drqs", "wp", "rota", "request", "adhoc"}
INVESTIGATION_STATUSES = {"open", "monitoring", "concluded", "abandoned"}
HYPOTHESIS_STATUSES = {"open", "supported", "refuted", "unk"}

# signatures/<slug>.md -- the known-error lifecycle.
SIGNATURE_STATUSES = {
    "suspected",
    "confirmed",
    "known-error",
    "fix-in-progress",
    "fixed",
    "retired",
}

# runbooks/<layer>/<slug>.md -- reliability-engineering-guild layering.
RUNBOOK_LAYERS = {"workflow", "component", "action"}

# corrections/<date>-<slug>.md -- `kctx retract`'s own kind, and the status a
# referrer row carries in that file. "unchanged:<evidence>" is a compound
# token (free-text evidence suffix), checked separately from this set.
CORRECTION_KINDS = {"retract", "dispute", "supersede"}
CORRECTION_ROW_STATUSES = {"pending", "corrected", "superseded", "unresolved"}
# Row statuses `kctx stale` treats as still needing a human look.
CORRECTION_OPEN_ROW_STATUSES = {"pending", "unresolved"}


def require_choice(value: str, allowed: set, field_name: str) -> str:
    if value not in allowed:
        raise KctxError(
            "malformed", f"{field_name}={value!r} not one of {sorted(allowed)}"
        )
    return value


@dataclass
class Asset:
    id: str
    kind: str
    name: str
    locator: str = ""
    aliases: List[str] = field(default_factory=list)
    owner: str = "unknown"
    owner_source: str = ""
    lifecycle: str = "active"
    inspect: str = ""
    projects: List[str] = field(default_factory=list)
    verified_at: Optional[str] = None
    ttl: Optional[str] = None
    notes: str = ""
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Asset":
        known = cls.__dataclass_fields__.keys()
        return cls(**{k: d[k] for k in known if k in d})


@dataclass
class Relationship:
    id: str
    type: str
    from_: str
    to: str
    status: str = "explicit"
    evidence: List[str] = field(default_factory=list)
    applicability: str = ""
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["from"] = d.pop("from_")
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Relationship":
        d = dict(d)
        if "from" in d:
            d["from_"] = d.pop("from")
        known = cls.__dataclass_fields__.keys()
        return cls(**{k: d[k] for k in known if k in d})


@dataclass
class ObservationSource:
    system: str
    locator: str
    asset: Optional[str] = None
    revision: Optional[str] = None
    role: str = "note"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ObservationSource":
        known = cls.__dataclass_fields__.keys()
        return cls(**{k: d[k] for k in known if k in d})


@dataclass
class Observation:
    id: str
    run: str
    source: ObservationSource
    observed_at: str
    status: str = "ok"
    command: Optional[str] = None
    environment: Optional[str] = None
    evidence: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None
    dirty: Optional[bool] = None
    dirty_diff_sha256: Optional[str] = None
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Observation":
        d = dict(d)
        d["source"] = ObservationSource.from_dict(d.get("source") or {})
        known = cls.__dataclass_fields__.keys()
        return cls(**{k: d[k] for k in known if k in d})


@dataclass
class CoverageEntry:
    item: str
    outcome: str
    evidence: List[str] = field(default_factory=list)
    reason: str = ""
    updated_at: str = ""
    prior_outcome: Optional[str] = None
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CoverageEntry":
        known = cls.__dataclass_fields__.keys()
        return cls(**{k: d[k] for k in known if k in d})


@dataclass
class Proposal:
    """Frontmatter shape for a proposal record.

    A new filing lives at proposals/<kind>/<date>-<slug>/proposal.md (plus
    sibling research/, evidence/ and gates.json); a proposal filed before the
    `evolve` skill existed is a single proposals/<kind>/<date>-<slug>.md file
    and is read in place, never migrated. The Markdown body sections
    (Context, Evidence, Proposed change, Research, Alternatives considered,
    Acceptance gates, Impact, Landing plan, References, Why general /
    justification, Decision log) are handled in proposals.py, which owns
    parsing and rendering the file as a whole; a legacy file only carries the
    five sections it was filed with.

    `type` may be a single string or a list, for a cross-cutting change.
    """

    id: str
    kind: str
    title: str
    status: str
    created: str
    origin: Optional[str] = None
    target: List[str] = field(default_factory=list)
    type: Optional[Any] = None
    updated: Optional[str] = None
    proposed_by: Optional[str] = None
    requested_by: Optional[str] = None
    source_session: Optional[str] = None
    project: Optional[str] = None
    swept_at: Optional[str] = None
    references: List[str] = field(default_factory=list)
    landed: List[str] = field(default_factory=list)
    decided_by: Optional[str] = None
    superseded_by: Optional[str] = None
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
