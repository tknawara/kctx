"""Authenticated source-to-admission publication and pinned retrieval.

Git's completed ref is the only publication point. Native Dolt candidate commits
and retained Git objects are durable before its expected-predecessor CAS. The
local lock coordinates cooperating writers; it is not a cross-store transaction.
"""

from __future__ import annotations

import platform
import shutil
import time
from collections.abc import Callable
from dataclasses import replace
from importlib.metadata import version
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from kctx.adapters.dolt.knowledge import KnowledgeDolt
from kctx.adapters.dolt.native import restore_backup
from kctx.adapters.files.knowledge import (
    canonical,
    decode,
    digest,
    durable_unlink,
    durable_write,
    load,
    save,
    writer_lock,
)
from kctx.adapters.git.knowledge import RELEASE_REF, GitReleases
from kctx.domain.ids import (
    ActorId,
    AssetId,
    AuthorityKeyId,
    ContentDigest,
    ContentId,
    DoltCommitId,
    OperationId,
    PlanId,
    PolicyDigest,
    ReleaseId,
    SnapshotId,
    SourceCaptureId,
    SourceId,
    SourceRevision,
)
from kctx.domain.json import JsonObject, JsonValue, object_value, text
from kctx.errors import KctxError
from kctx.semantics.checker import accepted, assess, assessment_gaps
from kctx.semantics.model import (
    KB,
    Atomic,
    Authority,
    Claim,
    ClaimRef,
    CommitOutcome,
    Conjunction,
    Context,
    Formula,
    Plan,
    ReceiptResult,
    SelectionPlan,
    SelectionState,
    SourceSelection,
    VerifiedApproval,
    VerifiedSelectionApproval,
    find_claim,
    narrower,
)
from kctx.semantics.wellformed import well_formed
from kctx.semantics.wire import (
    dec_context,
    dec_kb,
    dec_ref,
    dec_source_selection,
    dec_witness,
    enc_assessment,
    enc_context,
    enc_kb,
    enc_ref,
    enc_source_selection,
)
from kctx.semantics.workflow import apply_plan, apply_selection, plan_valid, selection_plan_valid
from kctx.services.knowledge_migration import Disposition, inspect_legacy, safe_restore_path
from kctx.services.knowledge_models import (
    AdmissionPlan,
    Approval,
    CaptureKind,
    ReleaseSelectionPlan,
    SourceCapture,
    decode_hex,
    decode_journal,
    decode_operation,
    decode_policy,
    decode_value,
)

TOOLCHAIN = "kctx-semantic-2.0.0"


def _formula_assets(formula: Formula, assets: frozenset[str]) -> frozenset[str]:
    """Exact structured identity relevance, never semantic scope or support."""
    if isinstance(formula, Atomic):
        return assets.intersection((formula.atom.subject, *formula.atom.args))
    if isinstance(formula, Conjunction):
        return _formula_assets(formula.left, assets) | _formula_assets(formula.right, assets)
    return frozenset()


def _claim_assets(claim: Claim, assets: frozenset[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            _formula_assets(claim.statement.formula, assets)
            | assets.intersection((claim.statement.scope.selector,))
        )
    )


class KnowledgeEngine:
    def __init__(
        self,
        repo: Path,
        store: Path,
        trusted_policy_digest: PolicyDigest | None = None,
        *,
        fault: Callable[[str], None] | None = None,
    ) -> None:
        self.git = GitReleases(repo)
        self.store = KnowledgeDolt(store)
        self.root = self.git.common / "kctx-knowledge"
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = self.store.path.parent / (self.store.path.name + ".knowledge.lock")
        owner_path = self.store.path.parent / (self.store.path.name + ".knowledge-owner.json")
        owner: JsonObject = {"schema_version": 2, "git_common": str(self.git.common)}
        with writer_lock(self.lock):
            if owner_path.exists() and load(owner_path) != owner:
                raise KctxError(
                    "conflict", "native Dolt store is owned by another authored repository"
                )
            save(owner_path, owner)
        self.bootstrap = trusted_policy_digest
        self.fault = fault

    def _artifact(self, identity: ContentDigest, release: ReleaseId | None = None) -> bytes:
        path = self.root / "artifacts" / identity.val
        if path.is_file():
            data = path.read_bytes()
        elif release:
            data = self.git.artifact(release.val, identity.val)
        else:
            raise KctxError("not-found", f"missing retained artifact {identity.val}")
        if digest(data) != identity.val:
            raise KctxError("conflict", "retained content digest mismatch")
        return data

    def _retain(self, data: bytes) -> ContentDigest:
        identity = ContentDigest(digest(data))
        durable_write(self.root / "artifacts" / identity.val, data)
        return identity

    def _toolchain_bytes(self) -> bytes:
        semantic_sources: JsonObject = {
            path.name: digest(path.read_bytes())
            for path in sorted((Path(__file__).parents[1] / "semantics").glob("*.py"))
        }
        return canonical(
            {
                "semantic_sources": semantic_sources,
                "python": platform.python_version(),
                "cryptography": version("cryptography"),
                "dolt": self.store.run("version", cwd=self.git.repo).strip(),
                "git": self.git.run("--version").strip(),
            }
        )

    def _policy(self, release: ReleaseId | None) -> tuple[PolicyDigest, JsonObject]:
        if release:
            identity = PolicyDigest(text(self.git.manifest(release.val)["policy"], "policy"))
            data = self._artifact(ContentDigest(identity.val), release)
            if self.bootstrap is None or identity != self.bootstrap:
                raise KctxError("conflict", "release policy does not match configured trust anchor")
        else:
            if self.bootstrap is None:
                raise KctxError(
                    "conflict", "bootstrap requires configured knowledge_policy_digest trust anchor"
                )
            data = (self.git.repo / ".kctx" / "knowledge-policy.json").read_bytes()
            identity = PolicyDigest(digest(data))
            if identity != self.bootstrap:
                raise KctxError(
                    "conflict", "bootstrap policy does not match configured trust anchor"
                )
        policy = decode_policy(decode(data))
        if release is None:
            self._retain(data)
        return identity, policy

    def _current(self) -> ReleaseId | None:
        current = self.git.current()
        return ReleaseId(current) if current else None

    def _release_operation(
        self, release: ReleaseId
    ) -> tuple[JsonObject, AdmissionPlan | ReleaseSelectionPlan, Approval]:
        manifest = self.git.manifest(release.val)
        plan = decode_operation(
            decode(
                self._artifact(
                    ContentDigest(text(manifest["plan_artifact"], "plan_artifact")), release
                )
            )
        )
        approval = Approval.decode(
            decode(
                self._artifact(
                    ContentDigest(text(manifest["approval_artifact"], "approval_artifact")), release
                )
            )
        )
        return manifest, plan, approval

    def _base(self, release: ReleaseId | None, policy: JsonObject) -> KB:
        if release is None:
            return KB(SnapshotId("bootstrap:" + text(policy["kb_id"], "kb_id")))
        manifest, plan, approval = self._release_operation(release)
        if manifest["toolchain"] != TOOLCHAIN:
            raise KctxError("malformed", "unsupported release toolchain")
        _, verified = self._verify(plan, approval, policy_source=release)
        if (
            manifest["operation"] != plan.id.val
            or manifest["predecessor"] != (plan.base.val if plan.base else None)
            or manifest["kb_id"] != policy["kb_id"]
        ):
            raise KctxError("conflict", "release differs from the authenticated operation")
        expected_kind = "admission" if isinstance(plan, AdmissionPlan) else "selection"
        if manifest["operation_kind"] != expected_kind or (
            isinstance(plan, ReleaseSelectionPlan)
            and manifest["retained_release"] != plan.retained.val
        ):
            raise KctxError("conflict", "release operation kind or retained target differs")
        expected_kb, captures, selected = self._evaluate_operation(
            plan, verified, policy, capture_release=release
        )
        commit = DoltCommitId(text(manifest["dolt_commit"], "dolt_commit"))
        kb = decode_value(dec_kb, self.store.read(commit, text(policy["kb_id"], "kb_id")))
        if kb != expected_kb or manifest["snapshot"] != kb.snapshot.val:
            raise KctxError(
                "conflict", "native generation differs from the authenticated candidate"
            )
        if self._sources(release) != plan.context.sources or self._selected(release) != selected:
            raise KctxError(
                "conflict",
                "release source or claim selection differs from the authenticated operation",
            )
        self._validate_native_operation(commit, plan, approval, captures)
        plan_artifact = digest(canonical(plan.wire()))
        approval_artifact = digest(canonical(approval.wire()))
        if (
            manifest["plan_artifact"] != plan_artifact
            or manifest["approval_artifact"] != approval_artifact
        ):
            raise KctxError("conflict", "release does not retain canonical signed operation bytes")
        if manifest["toolchain_artifact"] != plan.toolchain.val:
            raise KctxError("conflict", "release toolchain differs from the signed operation")
        expected_artifacts = {capture.content.val for capture in captures} | {
            plan.policy.val,
            plan_artifact,
            approval_artifact,
            plan.toolchain.val,
        }
        actual_artifacts = {text(value, "artifact") for value in self._list(manifest["artifacts"])}
        if actual_artifacts != expected_artifacts:
            raise KctxError(
                "conflict", "release artifact set differs from the authenticated operation"
            )
        for artifact in actual_artifacts:
            if digest(self.git.artifact(release.val, artifact)) != artifact:
                raise KctxError(
                    "conflict", "completed release has missing or corrupt retained bytes"
                )
        return kb

    def _evaluate_operation(
        self,
        plan: AdmissionPlan | ReleaseSelectionPlan,
        verified: VerifiedApproval | VerifiedSelectionApproval,
        policy: JsonObject,
        *,
        capture_release: ReleaseId | None = None,
    ) -> tuple[KB, tuple[SourceCapture, ...], tuple[ClaimRef, ...]]:
        base = self._base(plan.base, policy)
        if isinstance(plan, AdmissionPlan):
            if not isinstance(verified, VerifiedApproval):
                raise KctxError("conflict", "wrong verified operation capability")
            captures = self._validate_sources(plan, base, policy, capture_release=capture_release)
            result = apply_plan(
                base, plan.context, (), plan.semantic, trusted_approvals=(verified,)
            )
            if result.outcome is not CommitOutcome.APPLIED:
                raise KctxError(
                    "conflict", "complete approved candidate failed semantic validation"
                )
            candidate = result.kb
            selected = self._selected(plan.base) + tuple(
                claim.ref for claim in candidate.claims[len(base.claims) :]
            )
        else:
            if not isinstance(verified, VerifiedSelectionApproval):
                raise KctxError("conflict", "wrong verified operation capability")
            self._require_in_history(plan.retained, plan.base)
            self._validate_policy_context(plan.context, policy)
            if plan.context.sources != self._sources(plan.base):
                raise KctxError("conflict", "rollback must preserve current source selections")
            target = self._base(plan.retained, policy)
            result_selection = apply_selection(
                SelectionState(base, self._selected(plan.base)),
                plan.context,
                (),
                plan.semantic,
                trusted_approvals=(verified,),
                retained=(target,),
            )
            if result_selection.outcome is not CommitOutcome.APPLIED:
                raise KctxError(
                    "conflict", "approved retained selection failed semantic validation"
                )
            candidate = result_selection.state.kb
            selected = result_selection.state.selected
            prior = self.git.manifest(plan.base.val)
            captures = tuple(
                SourceCapture.decode(row)
                for row in self.store.rows(
                    "captures", DoltCommitId(text(prior["dolt_commit"], "dolt_commit"))
                )
            )
        self._assert_unused_snapshot(candidate.snapshot, plan.base)
        return candidate, captures, selected

    @staticmethod
    def _admission_row(
        plan: AdmissionPlan | ReleaseSelectionPlan, approval: Approval
    ) -> JsonObject:
        return {
            "id": plan.id.val,
            "actor": approval.key.val,
            "signature": approval.signature.hex(),
            "policy": plan.policy.val,
            "target_use": plan.context.intended_use,
            "base": plan.base.val if plan.base else None,
        }

    def _validate_native_operation(
        self,
        commit: DoltCommitId,
        plan: AdmissionPlan | ReleaseSelectionPlan,
        approval: Approval,
        captures: tuple[SourceCapture, ...],
    ) -> None:
        if self.store.rows("captures", commit) != [capture.wire() for capture in captures]:
            raise KctxError("conflict", "native capture rows differ from the signed operation")
        prior_rows: list[JsonObject] = []
        if plan.base:
            prior = self.git.manifest(plan.base.val)
            prior_rows = self.store.rows(
                "admissions", DoltCommitId(text(prior["dolt_commit"], "dolt_commit"))
            )
        if self.store.rows("admissions", commit) != [
            self._admission_row(plan, approval),
            *prior_rows,
        ]:
            raise KctxError(
                "conflict", "native admission history differs from the signed operation"
            )

    def _validate_release_hint(
        self,
        release: ReleaseId,
        plan: AdmissionPlan | ReleaseSelectionPlan,
        approval: Approval,
        policy: JsonObject,
        commit: DoltCommitId | None = None,
    ) -> None:
        manifest, retained_plan, retained_approval = self._release_operation(release)
        if (
            retained_plan != plan
            or retained_approval != approval
            or manifest["operation"] != plan.id.val
        ):
            raise KctxError("conflict", "journal release hint identifies another signed operation")
        if commit is not None and manifest["dolt_commit"] != commit.val:
            raise KctxError("conflict", "journal release and native candidate hints disagree")
        self._base(release, policy)

    def _retain_prepared(
        self,
        release: ReleaseId,
        plan: AdmissionPlan | ReleaseSelectionPlan,
        approval: Approval,
        policy: JsonObject,
    ) -> None:
        reference = "refs/kctx/prepared/" + plan.id.val
        previous = self.git.ref_revision(reference)
        if previous is not None:
            self._validate_release_hint(ReleaseId(previous), plan, approval, policy)
        self.git.run("update-ref", reference, release.val, previous or ("0" * len(release.val)))

    def capture(
        self,
        kind: CaptureKind,
        source: SourceId,
        revision: SourceRevision,
        content: bytes,
        observed_at: int,
    ) -> SourceCapture:
        if observed_at < 0:
            raise KctxError("malformed", "capture requires a nonnegative observation time")
        with writer_lock(self.lock):
            self._policy(self._current())
            return self._capture_bytes(kind, source, revision, content, observed_at)

    def _capture_bytes(
        self,
        kind: CaptureKind,
        source: SourceId,
        revision: SourceRevision,
        content: bytes,
        observed_at: int,
    ) -> SourceCapture:
        content_id = self._retain(content)
        metadata: JsonObject = {
            "kind": kind.value,
            "source": source.val,
            "revision": revision.val,
            "content": content_id.val,
            "observed_at": observed_at,
        }
        identity = SourceCaptureId(digest(canonical(metadata)))
        capture = SourceCapture(identity, kind, source, revision, content_id, observed_at)
        save(self.root / "captures" / (identity.val + ".json"), capture.wire())
        return capture

    def _capture(self, identity: SourceCaptureId, release: ReleaseId | None) -> SourceCapture:
        path = self.root / "captures" / (identity.val + ".json")
        if path.is_file():
            capture = SourceCapture.decode(load(path))
        elif release:
            manifest = self.git.manifest(release.val)
            rows = self.store.rows(
                "captures", DoltCommitId(text(manifest["dolt_commit"], "dolt_commit"))
            )
            found = next((row for row in rows if row["id"] == identity.val), None)
            if found is None:
                raise KctxError("not-found", "capture is not retained in pinned generation")
            capture = SourceCapture.decode(found)
        else:
            raise KctxError("not-found", "capture metadata missing")
        metadata = capture.wire()
        del metadata["id"]
        if capture.id != identity or digest(canonical(metadata)) != identity.val:
            raise KctxError("conflict", "capture identity mismatch")
        self._artifact(capture.content, release)
        return capture

    def _content_matches(
        self, identity: ContentId, capture: SourceCapture, release: ReleaseId | None
    ) -> bool:
        return identity == capture.content_identity or (
            identity.val.startswith("inventory:")
            and self._artifact(capture.content, release) == identity.val.encode()
        )

    def _validate_sources(
        self,
        plan: AdmissionPlan,
        base: KB,
        policy: JsonObject,
        *,
        capture_release: ReleaseId | None = None,
    ) -> tuple[SourceCapture, ...]:
        capture_release = capture_release or plan.base
        captures = tuple(self._capture(identity, capture_release) for identity in plan.captures)
        if len(set(plan.captures)) != len(plan.captures):
            raise KctxError("malformed", "duplicate capture identity")
        for observation in plan.semantic.candidate.observations:
            matching = [
                capture
                for capture in captures
                if capture.source == observation.source
                and capture.revision == observation.revision
                and capture.observed_at == observation.observed_at
            ]
            if not any(
                self._content_matches(observation.content, capture, capture_release)
                for capture in matching
            ):
                raise KctxError("conflict", "observation lacks exact retained capture provenance")
        for attestation in plan.semantic.candidate.attestations[len(base.attestations) :]:
            if attestation.authority != plan.semantic.authority.actor:
                raise KctxError("conflict", "new attestation is not bound to approving authority")
        previous = {item.source: item for item in self._sources(plan.base)}
        selected = {item.source: item for item in plan.context.sources}
        if len(selected) != len(plan.context.sources) or previous.keys() - selected.keys():
            raise KctxError(
                "conflict", "source selection duplicates or drops a previously selected source"
            )
        prior_capture_ids: set[SourceCaptureId] = set()
        if plan.base:
            prior_manifest = self.git.manifest(plan.base.val)
            prior_capture_ids = {
                SourceCaptureId(text(row["id"], "capture id"))
                for row in self.store.rows(
                    "captures", DoltCommitId(text(prior_manifest["dolt_commit"], "dolt_commit"))
                )
            }
        for selection in plan.context.sources:
            matching = tuple(
                capture
                for capture in captures
                if capture.source == selection.source
                and capture.revision == selection.revision
                and self._content_matches(selection.content, capture, capture_release)
            )
            if not matching:
                raise KctxError(
                    "conflict", "selected source identity has no exact retained capture"
                )
            if (
                selection.source in previous
                and selection != previous[selection.source]
                and not any(capture.id not in prior_capture_ids for capture in matching)
            ):
                raise KctxError(
                    "conflict",
                    "source replacement requires an explicit new capture, not an old retained observation",
                )
        self._validate_receipts(plan, base)
        self._validate_policy_context(plan.context, policy)
        return captures

    def _validate_policy_context(self, context: Context, policy: JsonObject) -> None:
        if context.policy.id.val != policy["policy_version"]:
            raise KctxError(
                "conflict", "semantic policy identity differs from trusted authority policy"
            )
        allowed = {
            ActorId(key)
            for key, value in object_value(policy["trusted_keys"]).items()
            if context.intended_use in self._list(object_value(value)["target_uses"])
        }
        if (
            len(context.policy.authorized_actors) != len(allowed)
            or set(context.policy.authorized_actors) != allowed
        ):
            raise KctxError(
                "conflict", "semantic authorized actors differ from trusted policy projection"
            )

    def _validate_query_context(
        self, release: ReleaseId, context: Context, policy: JsonObject
    ) -> None:
        self._validate_policy_context(context, policy)
        _, plan, _ = self._release_operation(release)
        approved = plan.context
        if (
            context.policy != approved.policy
            or context.intended_use != approved.intended_use
            or context.semantic_version != approved.semantic_version
            or context.ruleset != approved.ruleset
            or context.checker != approved.checker
            or context.sources != approved.sources
        ):
            raise KctxError(
                "conflict",
                "query policy, use, versions or sources differ from the authenticated release context",
            )
        if not narrower(context.target, approved.target):
            raise KctxError("conflict", "query target widens the authenticated release target")
        if context.now < approved.now:
            raise KctxError("conflict", "query time predates the authenticated publication context")

    @staticmethod
    def _validate_receipts(plan: AdmissionPlan, base: KB) -> None:
        execution_context = replace(plan.context, snapshot=plan.semantic.candidate.snapshot)
        for receipt in plan.semantic.candidate.receipts[len(base.receipts) :]:
            if (
                receipt.context != execution_context
                or receipt.context.checker.val != "kctx-2"
                or receipt.expires_at < execution_context.now
            ):
                raise KctxError(
                    "conflict", "new receipt must bind this actual named-checker execution context"
                )
            checked = next(
                (
                    result
                    for witness, result in accepted(
                        plan.semantic.candidate, execution_context, receipt.claim
                    )
                    if witness == receipt.witness
                ),
                None,
            )
            actual_result = ReceiptResult.PASS if checked is not None else ReceiptResult.FAIL
            actual_dependencies = checked.dependencies if checked is not None else ()
            if receipt.result is not actual_result or receipt.dependencies != actual_dependencies:
                raise KctxError(
                    "conflict",
                    "caller receipt differs from actual named-checker result or computed dependencies",
                )

    def _sources(self, release: ReleaseId | None) -> tuple[SourceSelection, ...]:
        if release is None:
            return ()
        return tuple(
            decode_value(dec_source_selection, value)
            for value in self._list(self.git.manifest(release.val)["sources"])
        )

    def _assert_unused_snapshot(self, snapshot: SnapshotId, base: ReleaseId | None) -> None:
        cursor = base
        while cursor is not None:
            manifest = self.git.manifest(cursor.val)
            if manifest["snapshot"] == snapshot.val:
                raise KctxError(
                    "conflict",
                    "immutable snapshot identity was already used by a completed release",
                )
            predecessor = manifest["predecessor"]
            cursor = (
                ReleaseId(text(predecessor, "predecessor")) if predecessor is not None else None
            )

    def _require_completed(self, release: ReleaseId) -> None:
        self._require_in_history(release, self._current())

    def _require_in_history(self, release: ReleaseId, completed: ReleaseId | None) -> None:
        cursor = completed
        while cursor is not None:
            if cursor == release:
                return
            predecessor = self.git.manifest(cursor.val)["predecessor"]
            cursor = (
                ReleaseId(text(predecessor, "predecessor")) if predecessor is not None else None
            )
        raise KctxError("not-found", "release is not in the completed publication history")

    def _selected(self, release: ReleaseId | None) -> tuple[ClaimRef, ...]:
        if release is None:
            return ()
        return tuple(
            decode_value(dec_ref, value)
            for value in self._list(self.git.manifest(release.val)["selected"])
        )

    def rollback(
        self, retained_release: ReleaseId, context: Context, authority_key: AuthorityKeyId
    ) -> ReleaseSelectionPlan:
        """Propose a signed forward selection, never rewind a completed pointer."""
        with writer_lock(self.lock):
            base_release = self._current()
            if base_release is None:
                raise KctxError("not-found", "retained selection requires a completed predecessor")
            self._require_completed(retained_release)
            policy_id, policy = self._policy(base_release)
            base = self._base(base_release, policy)
            retained = self._base(retained_release, policy)
            self._validate_policy_context(context, policy)
            if context.sources != self._sources(base_release):
                raise KctxError("conflict", "rollback must preserve current source selections")
            self._key(policy, authority_key, context.intended_use)
            material: JsonObject = {
                "base": base_release.val,
                "retained": retained_release.val,
                "context": object_value(enc_context(context)),
                "actor": authority_key.val,
                "policy": policy_id.val,
            }
            snapshot = SnapshotId("selection:" + digest(canonical(material)))
            self._assert_unused_snapshot(snapshot, base_release)
            semantic = SelectionPlan(
                OperationId("pending"),
                base.snapshot,
                retained.snapshot,
                snapshot,
                tuple(claim.ref for claim in retained.claims),
                ActorId(authority_key.val),
                context.policy.id,
                context.intended_use,
                context=context,
            )
            plan = ReleaseSelectionPlan(
                PlanId("0" * 64),
                base_release,
                retained_release,
                policy_id,
                context,
                semantic,
                self._retain(self._toolchain_bytes()),
            )
            identity = self._identity(plan)
            plan = replace(
                plan, id=identity, semantic=replace(semantic, id=OperationId(identity.val))
            )
            if not selection_plan_valid(
                SelectionState(base, self._selected(base_release)),
                context,
                plan.semantic,
                retained=(retained,),
            ):
                raise KctxError(
                    "conflict", "retained snapshot is not a compatible authorized selection"
                )
            save(self.root / "plans" / (identity.val + ".json"), plan.wire())
            return plan

    @staticmethod
    def _identity(plan: AdmissionPlan | ReleaseSelectionPlan) -> PlanId:
        record = plan.wire()
        del record["id"]
        semantic = object_value(record["plan"])
        del semantic["id"]
        record["plan"] = semantic
        return PlanId(digest(canonical(record)))

    def propose(self, candidate: JsonObject, target_use: str, now: int) -> AdmissionPlan:
        if set(candidate) != {"kb", "capture_ids", "context", "claim", "witness", "authority_key"}:
            raise KctxError(
                "malformed", "candidate requires kb,capture_ids,context,claim,witness,authority_key"
            )
        with writer_lock(self.lock):
            base_release = self._current()
            policy_id, policy = self._policy(base_release)
            base = self._base(base_release, policy)
            kb = decode_value(dec_kb, candidate["kb"])
            self._assert_unused_snapshot(kb.snapshot, base_release)
            context = decode_value(dec_context, candidate["context"])
            if (
                context.snapshot != base.snapshot
                or context.now != now
                or context.intended_use != target_use
            ):
                raise KctxError(
                    "conflict", "proposal context must identify exact base, time and intended use"
                )
            claim = decode_value(dec_ref, candidate["claim"])
            record = find_claim(kb, claim)
            if record is None:
                raise KctxError("malformed", "designated candidate claim missing")
            actor = AuthorityKeyId(text(candidate["authority_key"], "authority_key"))
            authority = Authority(
                actor=ActorId(actor.val),
                target=claim,
                intended_use=target_use,
                policy=context.policy.id,
                statement=record.statement,
                approved=kb,
                approvals=kb.claims[len(base.claims) :],
                context=context,
            )
            raw_ids = candidate["capture_ids"]
            if not isinstance(raw_ids, list):
                raise KctxError("malformed", "capture_ids must be an array")
            placeholder = PlanId("0" * 64)
            semantic = Plan(
                OperationId(placeholder.val),
                base.snapshot,
                kb,
                authority,
                claim,
                decode_value(dec_witness, candidate["witness"]),
            )
            plan = AdmissionPlan(
                placeholder,
                base_release,
                policy_id,
                tuple(SourceCaptureId(text(item, "capture_id")) for item in raw_ids),
                context,
                semantic,
                self._retain(self._toolchain_bytes()),
            )
            identity = self._identity(plan)
            plan = replace(
                plan, id=identity, semantic=replace(semantic, id=OperationId(identity.val))
            )
            self._key(policy, actor, target_use)
            self._validate_sources(plan, base, policy)
            if not plan_valid(base, context, plan.semantic):
                gaps = assessment_gaps(
                    plan.semantic.candidate,
                    replace(context, snapshot=plan.semantic.candidate.snapshot),
                    plan.semantic.claim,
                )
                raise KctxError(
                    "conflict",
                    "candidate rejected by calculus preflight"
                    + (f": {'; '.join(gaps)}" if gaps else ""),
                )
            save(self.root / "plans" / (identity.val + ".json"), plan.wire())
            return plan

    def _plan(self, identity: PlanId) -> AdmissionPlan | ReleaseSelectionPlan:
        plan = decode_operation(load(self.root / "plans" / (identity.val + ".json")))
        if (
            plan.id != identity
            or self._identity(plan) != identity
            or plan.semantic.id.val != identity.val
        ):
            raise KctxError("conflict", "plan content does not match canonical identity")
        return plan

    @staticmethod
    def _key(policy: JsonObject, identity: AuthorityKeyId, target_use: str) -> Ed25519PublicKey:
        keys = object_value(policy["trusted_keys"])
        if identity.val not in keys:
            raise KctxError("conflict", "untrusted approving key")
        key = object_value(keys[identity.val])
        if (
            set(key) != {"public_key", "target_uses"}
            or not isinstance(key["target_uses"], list)
            or target_use not in key["target_uses"]
        ):
            raise KctxError("conflict", "authority key is not authorized for intended use")
        return Ed25519PublicKey.from_public_bytes(decode_hex(key["public_key"], 32, "public_key"))

    def sign(self, identity: PlanId, private_key: Path, key_id: AuthorityKeyId) -> Approval:
        plan = self._plan(identity)
        if plan.actor != key_id:
            raise KctxError("conflict", "signer is not designated proposal authority")
        try:
            key = serialization.load_pem_private_key(private_key.read_bytes(), password=None)
        except (ValueError, TypeError) as exc:
            raise KctxError(
                "malformed", "approval requires an unencrypted valid PEM private key"
            ) from exc
        if not isinstance(key, Ed25519PrivateKey):
            raise KctxError("malformed", "approval requires Ed25519 PEM private key")
        approval = Approval(
            identity, key_id, key.sign(b"kctx-operation-v2\x00" + canonical(plan.wire()))
        )
        self._verify(plan, approval)
        return approval

    def _verify(
        self,
        plan: AdmissionPlan | ReleaseSelectionPlan,
        approval: Approval,
        *,
        policy_source: ReleaseId | None = None,
    ) -> tuple[JsonObject, VerifiedApproval | VerifiedSelectionApproval]:
        if plan.semantic.id.val != plan.id.val or self._identity(plan) != plan.id:
            raise KctxError(
                "conflict", "signed operation has inconsistent canonical inner and outer identities"
            )
        identity, policy = self._policy(policy_source or plan.base or self._current())
        if identity != plan.policy or approval.plan != plan.id or approval.key != plan.actor:
            raise KctxError("conflict", "approval is bound to different plan, policy or actor")
        if policy_source is None and plan.toolchain != ContentDigest(
            digest(self._toolchain_bytes())
        ):
            raise KctxError("stale", "operation toolchain inputs changed since proposal")
        declared_context = (
            plan.semantic.authority.context
            if isinstance(plan, AdmissionPlan)
            else plan.semantic.context
        )
        if declared_context != plan.context:
            raise KctxError("conflict", "signed semantic operation and service context differ")
        try:
            self._key(policy, approval.key, plan.context.intended_use).verify(
                approval.signature, b"kctx-operation-v2\x00" + canonical(plan.wire())
            )
        except InvalidSignature as exc:
            raise KctxError("conflict", "invalid detached approval signature") from exc
        return policy, VerifiedApproval(plan.semantic) if isinstance(
            plan, AdmissionPlan
        ) else VerifiedSelectionApproval(plan.semantic)

    def _phase(self, journal: JsonObject, phase: str) -> None:
        journal["phase"] = phase
        identity = PlanId(text(journal["id"], "id"))
        save(self.root / "journal" / (identity.val + ".json"), decode_journal(journal, identity))
        if self.fault is not None:
            self.fault(phase)

    def admit(self, identity: PlanId, approval: Approval) -> JsonObject:
        with writer_lock(self.lock):
            plan = self._plan(identity)
            self._verify(plan, approval)
            path = self.root / "journal" / (identity.val + ".json")
            journal: JsonObject
            if path.exists():
                journal = decode_journal(load(path), identity)
                if journal.get("approval") != approval.wire():
                    raise KctxError("conflict", "conflicting operation replay")
            else:
                journal = {
                    "schema_version": 2,
                    "id": identity.val,
                    "approval": approval.wire(),
                    "phase": "prepared",
                }
                if self._current() != plan.base:
                    raise KctxError("conflict", "expected predecessor changed")
                self._phase(journal, "prepared")
            return self._finish(plan, approval, journal)

    def _finish(
        self, plan: AdmissionPlan | ReleaseSelectionPlan, approval: Approval, journal: JsonObject
    ) -> JsonObject:
        journal = decode_journal(journal, plan.id)
        if journal["approval"] != approval.wire():
            raise KctxError(
                "conflict", "journal approval differs from the supplied signed operation"
            )
        policy, verified = self._verify(plan, approval)
        release_value = journal.get("release")
        release = ReleaseId(text(release_value, "release")) if release_value is not None else None
        candidate_kb, captures, selected = self._evaluate_operation(
            plan, verified, policy, capture_release=release
        )
        commit_value = journal.get("dolt_commit")
        commit = (
            DoltCommitId(text(commit_value, "dolt_commit")) if commit_value is not None else None
        )
        if commit is not None:
            hinted_kb = decode_value(
                dec_kb, self.store.read(commit, text(policy["kb_id"], "kb_id"))
            )
            if hinted_kb != candidate_kb:
                raise KctxError(
                    "conflict", "journal native candidate differs from the signed operation"
                )
            self._validate_native_operation(commit, plan, approval, captures)
        if release is not None:
            self._validate_release_hint(release, plan, approval, policy, commit)
        current = self._current()
        if release is not None and current == release:
            self._phase(journal, "published")
            return {"outcome": "already_applied", "release": release.val, "plan": plan.id.val}
        if current != plan.base:
            cursor = current
            while cursor is not None:
                manifest = self.git.manifest(cursor.val)
                if manifest["operation"] == plan.id.val:
                    self._validate_release_hint(cursor, plan, approval, policy)
                    return {
                        "outcome": "already_applied",
                        "release": cursor.val,
                        "plan": plan.id.val,
                    }
                predecessor = manifest["predecessor"]
                cursor = (
                    ReleaseId(text(predecessor, "predecessor")) if predecessor is not None else None
                )
            raise KctxError(
                "conflict", "expected predecessor changed; previous release remains published"
            )
        if commit is None:
            prior = self.git.manifest(plan.base.val) if plan.base else None
            commit = self.store.commit_candidate(
                plan.id,
                DoltCommitId(text(prior["dolt_commit"], "dolt_commit")) if prior else None,
                object_value(enc_kb(candidate_kb)),
                [capture.wire() for capture in captures],
                self._admission_row(plan, approval),
                text(policy["kb_id"], "kb_id"),
            )
            if self.fault is not None:
                self.fault("after_candidate_commit")
            journal["dolt_commit"] = commit.val
            self._phase(journal, "candidate")
            retained_kb = decode_value(
                dec_kb, self.store.read(commit, text(policy["kb_id"], "kb_id"))
            )
            if retained_kb != candidate_kb:
                raise KctxError(
                    "conflict", "completed native candidate differs from approved state"
                )
            self._validate_native_operation(commit, plan, approval, captures)
        if release is None:
            artifacts = {
                capture.content.val: self._artifact(capture.content, plan.base)
                for capture in captures
            }
            artifacts[plan.policy.val] = self._artifact(ContentDigest(plan.policy.val), plan.base)
            plan_content = canonical(plan.wire())
            approval_content = canonical(approval.wire())
            artifacts[digest(plan_content)] = plan_content
            artifacts[digest(approval_content)] = approval_content
            artifacts[plan.toolchain.val] = self._artifact(plan.toolchain, plan.base)
            artifact_ids: list[JsonValue] = [identity for identity in sorted(artifacts)]
            manifest: JsonObject = {
                "schema_version": 2,
                "semantic_version": "2.0.0",
                "snapshot": candidate_kb.snapshot.val,
                "kb_id": policy["kb_id"],
                "operation": plan.id.val,
                "predecessor": plan.base.val if plan.base else None,
                "dolt_commit": commit.val,
                "policy": plan.policy.val,
                "toolchain": TOOLCHAIN,
                "artifacts": artifact_ids,
                "plan_artifact": digest(plan_content),
                "approval_artifact": digest(approval_content),
            }
            manifest["toolchain_artifact"] = plan.toolchain.val
            manifest["selected"] = [object_value(enc_ref(ref)) for ref in selected]
            manifest["sources"] = [
                object_value(enc_source_selection(source)) for source in plan.context.sources
            ]
            manifest["operation_kind"] = (
                "admission" if isinstance(plan, AdmissionPlan) else "selection"
            )
            if isinstance(plan, ReleaseSelectionPlan):
                manifest["retained_release"] = plan.retained.val
            release = ReleaseId(
                self.git.prepare(manifest, plan.base.val if plan.base else None, artifacts)
            )
            self._retain_prepared(release, plan, approval, policy)
            if self.fault is not None:
                self.fault("after_manifest_commit")
            journal["release"] = release.val
            self._phase(journal, "manifest")
        self._validate_release_hint(release, plan, approval, policy, commit)
        self.git.publish(release.val, plan.base.val if plan.base else None)
        if self.fault is not None:
            self.fault("after_publish_cas")
        self._phase(journal, "published")
        return {"outcome": "applied", "release": release.val, "plan": plan.id.val}

    def recover(self) -> JsonObject:
        results: list[JsonValue] = []
        with writer_lock(self.lock):
            for path in sorted((self.root / "journal").glob("*.json")):
                identity = PlanId(path.stem)
                journal = decode_journal(load(path), identity)
                plan = self._plan(identity)
                approval = Approval.decode(object_value(journal["approval"]))
                try:
                    results.append(self._finish(plan, approval, journal))
                except KctxError as exc:
                    results.append({"plan": plan.id.val, "outcome": "conflict", "error": str(exc)})
        return {"operations": results}

    def context(
        self,
        claims: tuple[ClaimRef, ...],
        context: Context,
        limit: int = 20,
        continuation: JsonObject | None = None,
        release: ReleaseId | None = None,
        *,
        assets: tuple[AssetId, ...] | None = None,
    ) -> JsonObject:
        if limit < 1 or limit > 100:
            raise KctxError("malformed", "context limit must be between 1 and 100")
        query_input: JsonObject = {
            "claims": [object_value(enc_ref(ref)) for ref in claims],
            "context": object_value(enc_context(context)),
        }
        asset_ids = None if assets is None else frozenset(asset.val for asset in assets)
        if asset_ids is not None:
            query_input["assets"] = [identity for identity in sorted(asset_ids)]
        query = digest(canonical(query_input))
        offset = 0
        if continuation:
            if (
                set(continuation) != {"release", "offset", "query"}
                or continuation["query"] != query
            ):
                raise KctxError("conflict", "continuation belongs to another query/context")
            release = ReleaseId(text(continuation["release"], "release"))
            raw_offset = continuation["offset"]
            if type(raw_offset) is not int or raw_offset < 0:
                raise KctxError("malformed", "invalid continuation offset")
            offset = raw_offset
        release = release or self._current()
        if release is None:
            raise KctxError("not-found", "no completed knowledge release")
        self._require_completed(release)
        _, policy = self._policy(release)
        kb = self._base(release, policy)
        self._validate_query_context(release, context, policy)
        if context.snapshot != kb.snapshot:
            raise KctxError("conflict", "context snapshot does not match pinned release")
        if context.sources != self._sources(release):
            raise KctxError(
                "conflict", "query source selections differ from the pinned completed release"
            )
        wanted = set(claims)
        active = set(self._selected(release))
        asset_matches = (
            {}
            if asset_ids is None
            else {claim.ref: _claim_assets(claim, asset_ids) for claim in kb.claims}
        )
        selected = [
            claim
            for claim in kb.claims
            if claim.ref in active
            and (not wanted or claim.ref in wanted)
            and (asset_ids is None or bool(asset_matches[claim.ref]))
            and narrower(context.target, claim.statement.scope)
        ]
        page = selected[offset : offset + limit]
        records: list[JsonValue] = []
        wire = object_value(enc_kb(kb))
        for claim in page:
            ref = object_value(enc_ref(claim.ref))
            opposite = [
                other
                for other in kb.claims
                if other.statement.formula == claim.statement.formula
                and other.statement.scope == claim.statement.scope
                and other.statement.polarity != claim.statement.polarity
            ]
            relevant_refs = [ref] + [object_value(enc_ref(other.ref)) for other in opposite]
            records.append(
                {
                    "claim": {
                        "id": claim.id.val,
                        "revision": claim.revision.val,
                        "statement": next(
                            object_value(item)["statement"]
                            for item in self._list(wire["claims"])
                            if object_value(item)["id"] == claim.id.val
                            and object_value(item)["revision"] == claim.revision.val
                        ),
                    },
                    "assessment": object_value(enc_assessment(assess(kb, context, claim.ref))),
                    "contrary": [object_value(enc_ref(other.ref)) for other in opposite],
                    "attestations": [
                        item
                        for item in self._list(wire["attestations"])
                        if object_value(item)["claim"] in relevant_refs
                    ],
                    "derivations": [
                        item
                        for item in self._list(wire["derivations"])
                        if object_value(item)["claim"] in relevant_refs
                    ],
                    "receipts": [
                        item
                        for item in self._list(wire["receipts"])
                        if object_value(item)["claim"] in relevant_refs
                    ],
                }
            )
            if asset_ids is not None:
                record = object_value(records[-1])
                record["matched_assets"] = list(asset_matches[claim.ref])
                records[-1] = record
        end = offset + len(page)
        omitted = max(0, len(selected) - end)
        manifest = self.git.manifest(release.val)
        # Verify all pinned content before exposing assessments. Missing exact
        # source bytes is an explicit failure, never a HEAD/content fallback.
        for identity in self._list(manifest["artifacts"]):
            self._artifact(ContentDigest(text(identity, "artifact")), release)
        result: JsonObject = {
            "release": release.val,
            "snapshot": kb.snapshot.val,
            "records": records,
            "omitted": omitted,
            "complete": omitted == 0,
            "missing": [
                # Exact-ref diagnostics remain independent of relevance filtering.
                object_value(enc_ref(ref))
                for ref in claims
                if find_claim(kb, ref) is None
            ],
            "continuation": {"release": release.val, "offset": end, "query": query}
            if omitted
            else None,
            "provenance": {"manifest": manifest, "observations": wire["observations"]},
            "evidence_omitted": False,
        }
        result["scope_omitted"] = sum(
            1
            for claim in kb.claims
            if (not wanted or claim.ref in wanted)
            and not narrower(context.target, claim.statement.scope)
            and (asset_ids is None or bool(asset_matches[claim.ref]))
        )
        result["selection_omitted"] = sum(
            1
            for claim in kb.claims
            if claim.ref not in active
            and (not wanted or claim.ref in wanted)
            and (asset_ids is None or bool(asset_matches[claim.ref]))
        )
        result["not_selected"] = [
            object_value(enc_ref(ref))
            for ref in claims
            if find_claim(kb, ref) is not None and ref not in active
        ]
        result["provenance"] = {
            "manifest": manifest,
            "observations": wire["observations"],
            "corrections": wire["corrections"],
        }
        # The response has an explicit 64 KiB byte ceiling as well as a record
        # bound. Detailed evidence can be omitted, but this must be visible.
        if len(canonical(result)) > 65536:
            result["provenance"] = {
                "release": release.val,
                "dolt_commit": manifest["dolt_commit"],
                "policy": manifest["policy"],
                "plan_artifact": manifest["plan_artifact"],
                "approval_artifact": manifest["approval_artifact"],
            }
            for index, raw in enumerate(records):
                item = object_value(raw)
                for field in ("attestations", "derivations", "receipts", "contrary"):
                    item[field] = []
                records[index] = item
            result["evidence_omitted"] = True
            result["complete"] = False
        while len(canonical(result)) > 65536 and records:
            records.pop()
            end -= 1
            result["omitted"] = len(selected) - end
            result["continuation"] = {"release": release.val, "offset": end, "query": query}
            result["complete"] = False
        if len(canonical(result)) > 65536 or (page and not records):
            raise KctxError(
                "incomplete",
                "single claim or query exceeds bounded context; narrow the exact query",
            )
        return result

    @staticmethod
    def _list(value: JsonValue) -> list[JsonValue]:
        if not isinstance(value, list):
            raise KctxError("malformed", "expected record array")
        return value

    def explain(
        self, claim: ClaimRef, context: Context, release: ReleaseId | None = None
    ) -> JsonObject:
        return self.context((claim,), context, 1, release=release)

    def context_for_assets(
        self,
        assets: tuple[AssetId, ...],
        *,
        limit: int = 100,
        release: ReleaseId | None = None,
        continuation: JsonObject | None = None,
    ) -> JsonObject:
        """Read relevant claims under one release's authenticated evaluation context."""
        if continuation is not None:
            release = ReleaseId(text(continuation.get("release"), "continuation release"))
        release = release or self._current()
        if release is None:
            return {"status": "no_release", "release": None, "records": [], "complete": False}
        manifest, plan, _ = self._release_operation(release)
        context = replace(plan.context, snapshot=SnapshotId(text(manifest["snapshot"], "snapshot")))
        result = self.context((), context, limit, continuation, release, assets=assets)
        result["status"] = "available"
        result["context"] = object_value(enc_context(context))
        result["relevance"] = "exact asset ID in formula subject/arguments or scope selector"
        return result

    def backup(self, destination: Path) -> JsonObject:
        with writer_lock(self.lock):
            if destination.exists():
                raise KctxError("conflict", "backup destination already exists")
            release = self._current()
            if release is None:
                raise KctxError("not-found", "cannot back up an unpublished store")
            _, policy = self._policy(release)
            self._base(release, policy)
            destination.mkdir(parents=True)
            self.git.run(
                "bundle", "create", str((destination / "authored.bundle").resolve()), "--all"
            )
            authored_branch = self.git.run("symbolic-ref", "--quiet", "HEAD").strip()
            self.store.run("backup", "sync-url", (destination / "dolt").resolve().as_uri())
            shutil.copytree(self.root, destination / "operations")
            save(
                destination / "backup.json",
                {
                    "schema_version": 2,
                    "release": release.val,
                    "policy": self.git.manifest(release.val)["policy"],
                    "kb_id": policy["kb_id"],
                    "authored_branch": authored_branch,
                },
            )
            return {"backup": str(destination), "release": release.val}

    def restore(self, source: Path) -> JsonObject:
        with writer_lock(self.lock):
            if self._current() is not None or self.store.path.exists():
                raise KctxError(
                    "conflict",
                    "restore requires no published release and nonexistent Dolt destination",
                )
            if self.git.run("for-each-ref", "--format=%(refname)", "refs/heads").strip():
                raise KctxError("conflict", "restore requires an empty authored repository")
            metadata = load(source / "backup.json")
            if (
                set(metadata) != {"schema_version", "release", "policy", "kb_id", "authored_branch"}
                or type(metadata["schema_version"]) is not int
                or metadata["schema_version"] != 2
            ):
                raise KctxError("malformed", "unsupported backup fields or schema")
            PolicyDigest(text(metadata["policy"], "policy"))
            text(metadata["kb_id"], "kb_id")
            branch = text(metadata["authored_branch"], "authored_branch")
            if not branch.startswith("refs/heads/") or branch.removeprefix(
                "refs/heads/"
            ).startswith("-"):
                raise KctxError(
                    "malformed", "backup authored branch is not an exact branch reference"
                )
            self.git.run("check-ref-format", branch)
            release = ReleaseId(text(metadata["release"], "release"))
            self.git.run(
                "fetch",
                str((source / "authored.bundle").resolve()),
                RELEASE_REF + ":refs/kctx/restore-candidate",
                "refs/heads/*:refs/heads/*",
                "refs/tags/*:refs/tags/*",
                "refs/kctx/prepared/*:refs/kctx/prepared/*",
            )
            bundled_release = ReleaseId(
                self.git.run("rev-parse", "--verify", "refs/kctx/restore-candidate").strip()
            )
            if bundled_release != release:
                raise KctxError(
                    "conflict",
                    "backup metadata release differs from the bundle's completed publication ref",
                )
            restore_backup(source / "dolt", self.store.path, dolt_bin=self.store.binary)
            manifest = self.git.manifest(release.val)
            if manifest["policy"] != metadata["policy"] or manifest["kb_id"] != metadata["kb_id"]:
                raise KctxError("conflict", "backup metadata does not match pinned release")
            if self.bootstrap is None or self.bootstrap.val != manifest["policy"]:
                raise KctxError("conflict", "restore policy does not match configured trust anchor")
            _, policy = self._policy(release)
            kb = self._base(release, policy)
            if not well_formed(kb):
                raise KctxError("conflict", "restored generation violates semantic invariants")
            for artifact in self._list(manifest["artifacts"]):
                self._artifact(ContentDigest(text(artifact, "artifact")), release)
            shutil.copytree(
                source / "operations",
                self.root,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("writer.lock"),
            )
            branch = text(metadata["authored_branch"], "authored_branch")
            heads = self.git.run("for-each-ref", "--format=%(refname)", "refs/heads").splitlines()
            if branch in heads:
                self.git.run("checkout", branch.removeprefix("refs/heads/"))
            self.git.publish(release.val, None)
            return {"outcome": "restored", "release": release.val}

    def _rollback_migration(self, identity: PlanId, receipt: JsonObject) -> JsonObject:
        receipt_path = self.root / "migrations" / identity.val / "receipt.json"
        if receipt.get("state") == "rolled_back":
            return receipt
        receipt["state"] = "rolling_back"
        save(receipt_path, receipt)
        durable_unlink(self.root / "migration-candidates" / (identity.val + ".json"))
        receipt["state"] = "rolled_back"
        save(receipt_path, receipt)
        return receipt

    def migrate(
        self, source: Path, apply: bool = False, rollback: PlanId | None = None
    ) -> JsonObject:
        with writer_lock(self.lock):
            if rollback:
                receipt = load(self.root / "migrations" / rollback.val / "receipt.json")
                return self._rollback_migration(rollback, receipt)
            if source.is_dir():
                return self._migrate_legacy(source, apply)
            raw = source.read_bytes()
            try:
                envelope = decode(raw)
            except (ValueError, KctxError):
                return self._migrate_legacy(source, apply)
            if "candidate" not in envelope:
                return self._migrate_legacy(source, apply)
            identity = PlanId(digest(raw))
            directory = self.root / "migrations" / identity.val
            receipt_path = directory / "receipt.json"
            if receipt_path.exists():
                previous = load(receipt_path)
                if previous.get("state") == "rolling_back":
                    return self._rollback_migration(identity, previous)
                return previous
            accepted: JsonValue = None
            reason: str | None = None
            try:
                data = decode(raw)
                if (
                    data.get("schema_version") != 2
                    or data.get("semantic_version") != "2.0.0"
                    or set(data) != {"schema_version", "semantic_version", "candidate"}
                ):
                    raise ValueError("unknown or historical schema lacks exact source identities")
                candidate = object_value(data["candidate"])
                kb = dec_kb(candidate["kb"])
                if not well_formed(kb):
                    raise ValueError("candidate semantic invariants fail")
                accepted = candidate
            except (ValueError, KeyError, KctxError) as exc:
                reason = str(exc)
            receipt: JsonObject = {
                "schema_version": 2,
                "migration": identity.val,
                "state": "dry_run" if not apply else "quarantined" if reason else "candidate",
                "accepted": 0 if reason else 1,
                "quarantined": 1 if reason else 0,
                "reason": reason,
                "restore_point": identity.val,
                "published": False,
            }
            if apply:
                durable_write(directory / "source.bytes", raw)
                if accepted is not None:
                    save(
                        self.root / "migration-candidates" / (identity.val + ".json"),
                        object_value(accepted),
                    )
                # Receipt publication is the completed migration marker. Every
                # retained source and staged candidate is durable before it.
                save(receipt_path, receipt)
            return receipt

    def _migrate_legacy(self, source: Path, apply: bool) -> JsonObject:
        imported = inspect_legacy(source)
        directory = self.root / "migrations" / imported.id.val
        receipt_path = directory / "receipt.json"
        if receipt_path.exists():
            previous = load(receipt_path)
            if previous.get("state") == "rolling_back":
                return self._rollback_migration(imported.id, previous)
            return previous
        receipt = imported.report()
        receipt["state"] = (
            "dry_run" if not apply else "candidate" if receipt["accepted"] else "quarantined"
        )
        receipt["restore_point"] = imported.id.val
        receipt["source_kind"] = "legacy-authored"
        if not apply:
            return receipt
        self._policy(self._current())
        intent_path = directory / "intent.json"
        if intent_path.exists():
            observed_at = load(intent_path)["observed_at"]
            if type(observed_at) is not int:
                raise KctxError("malformed", "invalid migration capture timestamp")
        else:
            observed_at = int(time.time())
            save(
                intent_path,
                {"schema_version": 2, "migration": imported.id.val, "observed_at": observed_at},
            )
        captures: list[JsonValue] = []
        source_root = source.resolve() if source.is_dir() else source.resolve().parent
        accepted_paths = {
            item.path: item
            for item in imported.items
            if item.kind != "citation"
            and item.disposition in (Disposition.EXACT, Disposition.UNIQUE)
        }
        for retained in imported.files:
            durable_write(safe_restore_path(directory / "restore", retained.path), retained.data)
            item = accepted_paths.get(retained.path)
            if item is not None:
                capture = self._capture_bytes(
                    CaptureKind.DOCUMENT if item.kind == "document" else CaptureKind.SOURCE,
                    SourceId((source_root / retained.path).as_uri()),
                    SourceRevision("content:sha256:" + digest(retained.data)),
                    retained.data,
                    observed_at,
                )
                captures.append(
                    {
                        "path": retained.path,
                        "authored_id": item.authored_id,
                        "capture": capture.wire(),
                        "historical_revision": None,
                    }
                )
        for retained in imported.resolved_sources:
            capture = self._capture_bytes(
                CaptureKind.SOURCE,
                SourceId(retained.path),
                SourceRevision(retained.path.rsplit("#", 1)[1].split(":", 1)[0]),
                retained.data,
                observed_at,
            )
            captures.append(
                {
                    "path": retained.path,
                    "authored_id": None,
                    "capture": capture.wire(),
                    "historical_revision": capture.revision.val,
                }
            )
        candidate: JsonObject = {
            "schema_version": 2,
            "kind": "legacy-source-candidates",
            "migration": imported.id.val,
            "captures": captures,
            "claims": [],
            "items": receipt["items"],
            "requires_structured_proposal": True,
        }
        save(self.root / "migration-candidates" / (imported.id.val + ".json"), candidate)
        receipt["captures"] = captures
        save(receipt_path, receipt)
        return receipt

    def restore_migration(self, identity: PlanId, destination: Path) -> JsonObject:
        with writer_lock(self.lock):
            if destination.exists():
                raise KctxError("conflict", "migration restore requires a new destination")
            directory = self.root / "migrations" / identity.val
            receipt = load(directory / "receipt.json")
            entries = receipt.get("files")
            restored: list[JsonValue] = []
            if isinstance(entries, list):
                for raw in entries:
                    entry = object_value(raw)
                    relative = text(entry["path"], "path")
                    data = safe_restore_path(directory / "restore", relative).read_bytes()
                    if digest(data) != entry["content"]:
                        raise KctxError(
                            "conflict", "retained migration restore-point digest mismatch"
                        )
                    durable_write(safe_restore_path(destination, relative), data)
                    restored.append({"path": relative, "content": digest(data)})
            else:
                data = (directory / "source.bytes").read_bytes()
                if digest(data) != identity.val:
                    raise KctxError("conflict", "retained export restore-point digest mismatch")
                durable_write(destination / "source.json", data)
                restored.append({"path": "source.json", "content": digest(data)})
            result: JsonObject = {
                "schema_version": 2,
                "migration": identity.val,
                "destination": str(destination),
                "restored": restored,
                "published": False,
            }
            save(directory / "restore-receipt.json", result)
            return result
