"""Typed source collection and authenticated admission records."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import TypeVar

from kctx.domain.ids import (
    AuthorityKeyId,
    ContentDigest,
    ContentId,
    DoltCommitId,
    PlanId,
    PolicyDigest,
    ReleaseId,
    SourceCaptureId,
    SourceId,
    SourceRevision,
)
from kctx.domain.json import JsonObject, enum_value, integer, object_value, text, texts
from kctx.errors import KctxError
from kctx.semantics.model import Context, Plan, SelectionPlan
from kctx.semantics.wire import (
    dec_context,
    dec_plan,
    dec_selection_plan,
    enc_context,
    enc_plan,
    enc_selection_plan,
)

_T = TypeVar("_T")


def decode_value(parser: Callable[[object], _T], value: object) -> _T:
    """Translate a pure semantic codec's documented rejection at the IO boundary."""
    try:
        return parser(value)
    except ValueError as exc:
        raise KctxError("malformed", str(exc)) from exc


def decode_hex(value: object, size: int, field: str) -> bytes:
    raw = text(value, field)
    if len(raw) != size * 2 or any(char not in "0123456789abcdefABCDEF" for char in raw):
        raise KctxError("malformed", f"{field} requires exactly {size} hexadecimal bytes")
    return bytes.fromhex(raw)


def decode_policy(value: JsonObject) -> JsonObject:
    if set(value) != {"schema_version", "kb_id", "policy_version", "trusted_keys"}:
        raise KctxError("malformed", "invalid authority policy fields")
    if integer(value["schema_version"], "schema_version") != 2:
        raise KctxError("malformed", "unsupported authority policy schema")
    if (
        not text(value["kb_id"], "kb_id").strip()
        or not text(value["policy_version"], "policy_version").strip()
    ):
        raise KctxError("malformed", "empty authority policy identity")
    for raw_identity, raw_key in object_value(value["trusted_keys"]).items():
        AuthorityKeyId(raw_identity)
        key = object_value(raw_key, "trusted key")
        if set(key) != {"public_key", "target_uses"}:
            raise KctxError("malformed", "invalid trusted key fields")
        decode_hex(key["public_key"], 32, "public_key")
        uses = texts(key["target_uses"], "target_uses")
        if not uses or len(set(uses)) != len(uses) or any(not use.strip() for use in uses):
            raise KctxError("malformed", "target_uses requires distinct nonempty strings")
    return value


def decode_journal(value: JsonObject, identity: PlanId) -> JsonObject:
    required = {"schema_version", "id", "approval", "phase"}
    if not required <= value.keys() or value.keys() - required - {"dolt_commit", "release"}:
        raise KctxError("malformed", "invalid operation journal fields")
    if (
        integer(value["schema_version"], "schema_version") != 2
        or PlanId(text(value["id"], "id")) != identity
    ):
        raise KctxError("malformed", "operation journal identity or version mismatch")
    phase = text(value["phase"], "phase")
    expected: dict[str, set[str]] = {
        "prepared": set(),
        "candidate": {"dolt_commit"},
        "manifest": {"dolt_commit", "release"},
        "published": {"dolt_commit", "release"},
    }
    if phase not in expected or value.keys() - required != expected[phase]:
        raise KctxError("malformed", "invalid operation journal phase or object hints")
    if "dolt_commit" in value:
        DoltCommitId(text(value["dolt_commit"], "dolt_commit"))
    if "release" in value:
        ReleaseId(text(value["release"], "release"))
    approval = Approval.decode(object_value(value["approval"]))
    if approval.plan != identity:
        raise KctxError("malformed", "operation journal approval identifies another plan")
    return value


class CaptureKind(Enum):
    SOURCE = "source"
    PR = "pr"
    DOCUMENT = "document"


@dataclass(frozen=True, slots=True)
class SourceCapture:
    id: SourceCaptureId
    kind: CaptureKind
    source: SourceId
    revision: SourceRevision
    content: ContentDigest
    observed_at: int

    @property
    def content_identity(self) -> ContentId:
        """Project a retained SHA256 artifact into the opaque semantic identity."""
        return ContentId(self.content.val)

    def wire(self) -> JsonObject:
        return {
            "id": self.id.val,
            "kind": self.kind.value,
            "source": self.source.val,
            "revision": self.revision.val,
            "content": self.content.val,
            "observed_at": self.observed_at,
        }

    @classmethod
    def decode(cls, value: JsonObject) -> SourceCapture:
        if set(value) != {"id", "kind", "source", "revision", "content", "observed_at"}:
            raise KctxError("malformed", "invalid capture record fields")
        observed_at = integer(value["observed_at"], "observed_at")
        if observed_at < 0:
            raise KctxError("malformed", "negative capture observation time")
        return cls(
            SourceCaptureId(text(value["id"], "id")),
            enum_value(CaptureKind, value["kind"], "kind"),
            SourceId(text(value["source"], "source")),
            SourceRevision(text(value["revision"], "revision")),
            ContentDigest(text(value["content"], "content")),
            observed_at,
        )


@dataclass(frozen=True, slots=True)
class AdmissionPlan:
    id: PlanId
    base: ReleaseId | None
    policy: PolicyDigest
    captures: tuple[SourceCaptureId, ...]
    context: Context
    semantic: Plan
    toolchain: ContentDigest

    @property
    def actor(self) -> AuthorityKeyId:
        return AuthorityKeyId(self.semantic.authority.actor.val)

    def wire(self) -> JsonObject:
        return {
            "schema_version": 2,
            "kind": "admission",
            "id": self.id.val,
            "base": self.base.val if self.base else None,
            "policy": self.policy.val,
            "captures": [item.val for item in self.captures],
            "context": object_value(enc_context(self.context)),
            "plan": object_value(enc_plan(self.semantic)),
            "toolchain": self.toolchain.val,
        }

    @classmethod
    def decode(cls, value: JsonObject) -> AdmissionPlan:
        if (
            set(value)
            != {
                "schema_version",
                "kind",
                "id",
                "base",
                "policy",
                "captures",
                "context",
                "plan",
                "toolchain",
            }
            or value["kind"] != "admission"
        ):
            raise KctxError("malformed", "invalid admission plan fields")
        captures = value["captures"]
        if integer(value["schema_version"], "schema_version") != 2 or not isinstance(
            captures, list
        ):
            raise KctxError("malformed", "invalid admission plan schema")
        return cls(
            PlanId(text(value["id"], "id")),
            ReleaseId(text(value["base"], "base")) if value["base"] is not None else None,
            PolicyDigest(text(value["policy"], "policy")),
            tuple(SourceCaptureId(text(item, "capture")) for item in captures),
            decode_value(dec_context, value["context"]),
            decode_value(dec_plan, value["plan"]),
            ContentDigest(text(value["toolchain"], "toolchain")),
        )


@dataclass(frozen=True, slots=True)
class ReleaseSelectionPlan:
    id: PlanId
    base: ReleaseId
    retained: ReleaseId
    policy: PolicyDigest
    context: Context
    semantic: SelectionPlan
    toolchain: ContentDigest

    @property
    def actor(self) -> AuthorityKeyId:
        actor = self.semantic.actor
        if actor is None:
            raise KctxError("malformed", "retained selection requires an approving actor")
        return AuthorityKeyId(actor.val)

    def wire(self) -> JsonObject:
        return {
            "schema_version": 2,
            "kind": "selection",
            "id": self.id.val,
            "base": self.base.val,
            "retained": self.retained.val,
            "policy": self.policy.val,
            "context": object_value(enc_context(self.context)),
            "plan": object_value(enc_selection_plan(self.semantic)),
            "toolchain": self.toolchain.val,
        }

    @classmethod
    def decode(cls, value: JsonObject) -> ReleaseSelectionPlan:
        if (
            set(value)
            != {
                "schema_version",
                "kind",
                "id",
                "base",
                "retained",
                "policy",
                "context",
                "plan",
                "toolchain",
            }
            or integer(value["schema_version"], "schema_version") != 2
            or value["kind"] != "selection"
        ):
            raise KctxError("malformed", "invalid retained-selection plan schema")
        return cls(
            PlanId(text(value["id"], "id")),
            ReleaseId(text(value["base"], "base")),
            ReleaseId(text(value["retained"], "retained")),
            PolicyDigest(text(value["policy"], "policy")),
            decode_value(dec_context, value["context"]),
            decode_value(dec_selection_plan, value["plan"]),
            ContentDigest(text(value["toolchain"], "toolchain")),
        )


def decode_operation(value: JsonObject) -> AdmissionPlan | ReleaseSelectionPlan:
    if value.get("kind") == "admission":
        return AdmissionPlan.decode(value)
    if value.get("kind") == "selection":
        return ReleaseSelectionPlan.decode(value)
    raise KctxError("malformed", "unknown knowledge operation kind")


@dataclass(frozen=True, slots=True)
class Approval:
    plan: PlanId
    key: AuthorityKeyId
    signature: bytes

    def wire(self) -> JsonObject:
        return {
            "schema_version": 2,
            "plan": self.plan.val,
            "key": self.key.val,
            "signature": self.signature.hex(),
        }

    @classmethod
    def decode(cls, value: JsonObject) -> Approval:
        if (
            set(value) != {"schema_version", "plan", "key", "signature"}
            or integer(value["schema_version"], "schema_version") != 2
        ):
            raise KctxError("malformed", "invalid approval envelope")
        return cls(
            PlanId(text(value["plan"], "plan")),
            AuthorityKeyId(text(value["key"], "key")),
            decode_hex(value["signature"], 64, "signature"),
        )
