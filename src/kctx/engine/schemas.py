"""Closed, strict JSON-RPC parameter schemas; published during initialization."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class Params(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Initialize(Params):
    protocol_version: Literal["1"]
    capabilities: list[str] = Field(default_factory=list)


class Target(Params):
    target: str


Limit = Annotated[int, Field(ge=1, le=1000)]


class Uses(Target):
    limit: Limit = 50
    include_illus: bool = False


class Impact(Target):
    depth: Annotated[int, Field(ge=1, le=10)] = 3
    rel: Annotated[list[str], Field(max_length=32)] | None = None
    limit: Limit = 100


class SourcePaths(Target):
    revision: str = "HEAD"
    limit: Limit = 1000


class Diff(Params):
    kb_sha_a: str
    kb_sha_b: str
    limit: Limit = 200


class Sync(Params):
    rebuild: bool = False
    history: Limit | None = None


class Check(Params):
    sample_ids: list[str] | None = None


class Capture(Params):
    kind: Literal["source", "pr", "document"]
    source: str
    revision: str
    content_base64: str
    observed_at: Annotated[int, Field(ge=0)]


class Propose(Params):
    candidate: dict[str, JsonValue]
    target_use: str
    now: int


class Admit(Params):
    plan: str
    approval: dict[str, JsonValue]


class Rollback(Params):
    release: str
    context: dict[str, JsonValue]
    key_id: str


class KnowledgeContext(Params):
    context: dict[str, JsonValue]
    claims: list[dict[str, JsonValue]]
    release: str | None = None
    limit: Annotated[int, Field(ge=1, le=100)] = 20
    continuation: dict[str, JsonValue] | None = None


class Explain(Params):
    context: dict[str, JsonValue]
    claim: dict[str, JsonValue]
    release: str | None = None


class Home(Params):
    ident: str


class AuthoredContext(Home):
    depth: Annotated[int, Field(ge=0, le=10)] = 2


class CiteCode(Params):
    kind: Literal["code"]
    repo: str
    path: str
    line_range: str
    sym: str | None = None
    rev: str | None = None
    ttl: str = "14d"
    allow_dirty: bool = False
    sens: Literal["public", "internal", "restricted"] | None = None
    redact: str | None = None


class CiteProposal(Params):
    kind: Literal["proposal"]
    id: str
    ttl: str | None = None


class CitationFields(Params):
    repo: str = ""
    rev: str = ""
    n: str = ""
    id: str = ""
    name: str = ""
    env: str = ""
    asset: str = ""
    service: str = ""
    sys: str = ""
    q: str = ""
    url: str = ""
    section: str = ""
    date: str = ""
    where: str = ""
    proposal: str = ""
    gate: str = ""
    outcome: str = ""
    path: str = ""
    state: str = ""
    value: str = ""
    version: str = ""
    rows: str = ""
    ev: str = ""
    result: str = ""
    window: str = ""
    quote: str = ""
    modified: str = ""
    who: str = ""
    seen: str = ""
    ttl: str = ""
    sens: Literal["public", "internal", "restricted"] = "internal"
    redact: str = ""
    note: str = ""


class CiteOther(Params):
    kind: Literal[
        "commit",
        "pr",
        "ticket",
        "breg",
        "deploy",
        "query",
        "doc",
        "web",
        "usr",
        "ev",
        "gate",
        "record",
        "metric",
        "log",
        "data",
    ]
    fields: CitationFields


class CiteMake(Params):
    citation: Annotated[CiteCode | CiteProposal | CiteOther, Field(discriminator="kind")]


class CiteCheck(Params):
    paths: list[str] = Field(default_factory=list)
    inline_line: str | None = None
    touch: bool = False
    touch_all: bool = False
    mark: bool = False


class CiteStale(Params):
    paths: list[str]
    offline: bool = False


class CiteRender(Params):
    target: str
    fmt: Literal["plain", "md", "html", "slack"] = "plain"
    audience: Literal["internal", "external"] = "internal"
    do_check: bool = False


METHODS: dict[str, type[Params]] = {
    "initialize": Initialize,
    "shutdown": Params,
    "graph.status": Params,
    "graph.refresh": Params,
    "graph.uses": Uses,
    "graph.source_paths": SourcePaths,
    "graph.impact": Impact,
    "graph.diff": Diff,
    "graph.sync": Sync,
    "graph.check": Check,
    "knowledge.capture": Capture,
    "knowledge.propose": Propose,
    "knowledge.admit": Admit,
    "knowledge.context": KnowledgeContext,
    "knowledge.explain": Explain,
    "knowledge.rollback": Rollback,
    "knowledge.recover": Params,
    "authored.context": AuthoredContext,
    "authored.home": Home,
    "authored.uses": Target,
    "cite.make": CiteMake,
    "cite.check": CiteCheck,
    "cite.stale": CiteStale,
    "cite.render": CiteRender,
}
