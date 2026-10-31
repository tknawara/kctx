"""Closed domain vocabulary; external strings are decoded at boundaries."""

from enum import Enum


class AssetKind(Enum):
    ALERT = "alert"
    API = "api"
    DASHBOARD = "dashboard"
    DEPLOYMENT = "deployment"
    DOC = "doc"
    ENVIRONMENT = "environment"
    OTHER = "other"
    PACKAGE = "package"
    PIPELINE = "pipeline"
    REPO = "repo"
    RUNBOOK = "runbook"
    SCHEMA = "schema"
    SERVICE = "service"
    STORE = "store"


class Lifecycle(Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


class RelationshipType(Enum):
    ALERTS_ON = "alerts-on"
    CONSUMES = "consumes"
    DEFINES_CONTRACT_FOR = "defines-contract-for"
    DEPENDS_ON = "depends-on"
    DEPLOYS = "deploys"
    DOCUMENTS = "documents"
    IMPLEMENTS = "implements"
    MONITORS = "monitors"
    OWNED_BY = "owned-by"
    PRODUCES = "produces"


class RelationshipStatus(Enum):
    CONFIRMED = "confirmed"
    DISPUTED = "disputed"
    EXPLICIT = "explicit"
    INFERRED = "inferred"
    RETIRED = "retired"


class ObservationSystem(Enum):
    BBGITHUB = "bbgithub"
    DEPLOYMENT = "deployment"
    DOC = "doc"
    GIT = "git"
    GRAFANA = "grafana"
    HUMIO = "humio"
    METRICS = "metrics"
    OTHER = "other"


class ObservationRole(Enum):
    CODE = "code"
    CONTRACT = "contract"
    DEPLOYMENT = "deployment"
    DOC = "doc"
    NOTE = "note"
    RUNTIME = "runtime"


class ObservationStatus(Enum):
    DENIED = "denied"
    ERROR = "error"
    NO_DATA = "no-data"
    NOT_FOUND = "not-found"
    OK = "ok"
    PARTIAL = "partial"
    TIMEOUT = "timeout"
    TRUNCATED = "truncated"


class CoverageOutcome(Enum):
    INCONCLUSIVE = "inconclusive"
    NEEDS_RECHECK = "needs-recheck"
    NOT_APPLICABLE = "not-applicable"
    NOT_EXAMINED = "not-examined"
    SUPPORTED = "supported"
    UNAVAILABLE = "unavailable"
    VIOLATED = "violated"


class ProposalKind(Enum):
    CONFIG = "config"
    DECISION = "decision"
    OTHER = "other"
    SKILL = "skill"
    STEWARD = "steward"


class ProposalType(Enum):
    AGENT = "agent"
    KB_TOOLING = "kb-tooling"
    MEMORY = "memory"
    MODULE = "module"
    NEW_SKILL = "new-skill"
    SETTINGS = "settings"
    SKILL_REFINEMENT = "skill-refinement"


class ProposalStatus(Enum):
    ACCEPTED = "accepted"
    APPLIED = "applied"
    DEFERRED = "deferred"
    DRAFT = "draft"
    LANDING = "landing"
    PROPOSED = "proposed"
    REGRESSED = "regressed"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    VERIFIED = "verified"


class ProposalOrigin(Enum):
    CONSOLIDATION = "consolidation"
    OTHER = "other"
    REVIEW_FINDING = "review-finding"
    STEWARD = "steward"
    SUGGEST_SKILLS = "suggest-skills"
    UNK = "unk"
    USER_REQUEST = "user-request"


class GateOutcome(Enum):
    FAIL = "fail"
    PASS = "pass"
    UNK = "unk"


class GateWhen(Enum):
    DEPLOY = "deploy"
    LAND = "land"
    USE = "use"


class RunMode(Enum):
    ADVICE = "advice"
    AUTHORING = "authoring"
    REVIEW = "review"


class KtloStatus(Enum):
    BLOCKED = "blocked"
    DONE = "done"
    IN_PROGRESS = "in-progress"
    INVESTIGATING = "investigating"
    N_A = "n/a"
    TODO = "todo"


class InvestigationTrigger(Enum):
    ADHOC = "adhoc"
    ALERT = "alert"
    DRQS = "drqs"
    REQUEST = "request"
    ROTA = "rota"
    WP = "wp"


class InvestigationStatus(Enum):
    ABANDONED = "abandoned"
    CONCLUDED = "concluded"
    MONITORING = "monitoring"
    OPEN = "open"


class HypothesisStatus(Enum):
    OPEN = "open"
    REFUTED = "refuted"
    SUPPORTED = "supported"
    UNK = "unk"


class SignatureStatus(Enum):
    CONFIRMED = "confirmed"
    FIX_IN_PROGRESS = "fix-in-progress"
    FIXED = "fixed"
    KNOWN_ERROR = "known-error"
    RETIRED = "retired"
    SUSPECTED = "suspected"


class RunbookLayer(Enum):
    ACTION = "action"
    COMPONENT = "component"
    WORKFLOW = "workflow"


class CorrectionKind(Enum):
    DISPUTE = "dispute"
    RETRACT = "retract"
    SUPERSEDE = "supersede"


class CorrectionRowStatus(Enum):
    CORRECTED = "corrected"
    PENDING = "pending"
    SUPERSEDED = "superseded"
    UNRESOLVED = "unresolved"


class RunState(Enum):
    OPEN = "open"


class Readiness(Enum):
    BLOCKED = "blocked"
    PARTIAL = "partial"
    READY = "ready"
