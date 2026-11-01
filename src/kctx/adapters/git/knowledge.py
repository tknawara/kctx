"""Immutable Git release manifests with an expected-predecessor CAS."""

from __future__ import annotations

import subprocess
from pathlib import Path

from kctx.adapters.files.knowledge import canonical, decode
from kctx.domain.ids import (
    ClaimId,
    ClaimRevision,
    ContentDigest,
    ContentId,
    DoltCommitId,
    PlanId,
    PolicyDigest,
    ReleaseId,
    SnapshotId,
    SourceId,
    SourceRevision,
)
from kctx.domain.json import JsonObject, integer, object_value, text, texts
from kctx.errors import KctxError
from kctx.semantics.workflow_wire import dec_named_context

RELEASE_REF = "refs/kctx/knowledge"


def _decode_manifest(value: JsonObject) -> JsonObject:
    required = {
        "schema_version",
        "semantic_version",
        "snapshot",
        "kb_id",
        "operation",
        "predecessor",
        "dolt_commit",
        "policy",
        "toolchain",
        "artifacts",
        "plan_artifact",
        "approval_artifact",
        "toolchain_artifact",
        "selected",
        "sources",
        "operation_kind",
    }
    schema = integer(value.get("schema_version"), "schema_version")
    if schema == 3:
        required.remove("sources")
        required.add("contexts")
    kind = value.get("operation_kind")
    expected: set[str] = required | ({"retained_release"} if kind == "selection" else set())
    if kind not in ("admission", "selection") or set(value) != expected:
        raise KctxError("malformed", "invalid completed-release manifest fields")
    if schema not in (2, 3) or value["semantic_version"] != "2.0.0":
        raise KctxError("malformed", "unsupported completed-release manifest version")
    SnapshotId(text(value["snapshot"], "snapshot"))
    PlanId(text(value["operation"], "operation"))
    DoltCommitId(text(value["dolt_commit"], "dolt_commit"))
    PolicyDigest(text(value["policy"], "policy"))
    if (
        not text(value["kb_id"], "kb_id").strip()
        or not text(value["toolchain"], "toolchain").strip()
    ):
        raise KctxError("malformed", "empty completed-release identity")
    if value["predecessor"] is not None:
        ReleaseId(text(value["predecessor"], "predecessor"))
    if kind == "selection":
        ReleaseId(text(value["retained_release"], "retained_release"))
    artifacts = texts(value["artifacts"], "artifacts")
    if len(set(artifacts)) != len(artifacts):
        raise KctxError("malformed", "duplicate retained artifact identity")
    for artifact in artifacts:
        ContentDigest(artifact)
    for field in ("policy", "plan_artifact", "approval_artifact", "toolchain_artifact"):
        required_artifact = ContentDigest(text(value[field], field))
        if required_artifact.val not in artifacts:
            raise KctxError("malformed", "required release artifact is not retained")
    selected = value["selected"]
    if not isinstance(selected, list):
        raise KctxError("malformed", "release selection must be an array")
    refs: set[tuple[ClaimId, ClaimRevision]] = set()
    for raw in selected:
        ref = object_value(raw)
        if set(ref) != {"id", "revision"}:
            raise KctxError("malformed", "invalid selected claim reference")
        claim_ref = (
            ClaimId(text(ref["id"], "id")),
            ClaimRevision(text(ref["revision"], "revision")),
        )
        if claim_ref in refs:
            raise KctxError("malformed", "duplicate selected claim reference")
        refs.add(claim_ref)
    if schema == 3:
        contexts = value["contexts"]
        if not isinstance(contexts, list) or not contexts:
            raise KctxError("malformed", "release contexts must be a nonempty array")
        try:
            named = tuple(dec_named_context(raw) for raw in contexts)
        except ValueError as exc:
            raise KctxError("malformed", str(exc)) from exc
        if len({entry.id for entry in named}) != len(named):
            raise KctxError("malformed", "duplicate named context identity")
        return value
    sources = value["sources"]
    if not isinstance(sources, list):
        raise KctxError("malformed", "release sources must be an array")
    source_ids: set[SourceId] = set()
    for raw in sources:
        source = object_value(raw)
        if set(source) != {"source", "revision", "content"}:
            raise KctxError("malformed", "invalid selected source reference")
        source_id = SourceId(text(source["source"], "source"))
        SourceRevision(text(source["revision"], "revision"))
        ContentId(text(source["content"], "content"))
        if source_id in source_ids:
            raise KctxError("malformed", "duplicate selected source identity")
        source_ids.add(source_id)
    return value


class GitReleases:
    def __init__(self, repo: Path) -> None:
        self.repo = repo.resolve()
        self.run("rev-parse", "--git-dir")
        self.common = Path(
            self.run("rev-parse", "--path-format=absolute", "--git-common-dir").strip()
        )

    def run(self, *args: str, data: bytes | None = None) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.repo), *args], input=data, capture_output=True, check=False
        )
        if result.returncode:
            raise KctxError("conflict", result.stderr.decode(errors="replace").strip())
        return result.stdout.decode()

    def current(self) -> str | None:
        return self.ref_revision(RELEASE_REF)

    def ref_revision(self, reference: str) -> str | None:
        self.run("check-ref-format", reference)
        result = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "--verify", "--quiet", reference],
            capture_output=True,
            check=False,
        )
        if result.returncode == 1:
            return None
        if result.returncode:
            raise KctxError("malformed", result.stderr.decode(errors="replace"))
        return result.stdout.decode().strip()

    def manifest(self, revision: str) -> JsonObject:
        if len(revision) not in (40, 64) or any(c not in "0123456789abcdef" for c in revision):
            raise KctxError("malformed", "release must be an exact Git object identity")
        result = subprocess.run(
            ["git", "-C", str(self.repo), "show", f"{revision}:manifest.json"],
            capture_output=True,
            check=False,
        )
        if result.returncode:
            raise KctxError("not-found", "completed-release manifest object is unavailable")
        return _decode_manifest(decode(result.stdout))

    def prepare(
        self, manifest: JsonObject, predecessor: str | None, artifacts: dict[str, bytes]
    ) -> str:
        blob = self.run("hash-object", "-w", "--stdin", data=canonical(manifest)).strip()
        entries: list[str] = []
        for identity, data in sorted(artifacts.items()):
            if len(identity) != 64 or any(c not in "0123456789abcdef" for c in identity):
                raise KctxError("malformed", "invalid retained artifact identity")
            obj = self.run("hash-object", "-w", "--stdin", data=data).strip()
            entries.append(f"100644 blob {obj}\t{identity}\n")
        artifact_tree = self.run("mktree", data="".join(entries).encode()).strip()
        tree = self.run(
            "mktree",
            data=f"100644 blob {blob}\tmanifest.json\n040000 tree {artifact_tree}\tartifacts\n".encode(),
        ).strip()
        parents = ["-p", predecessor] if predecessor else []
        return self.run(
            "-c",
            "user.name=kctx-knowledge",
            "-c",
            "user.email=kctx@localhost",
            "commit-tree",
            tree,
            *parents,
            "-m",
            "Publish approved knowledge generation",
        ).strip()

    def artifact(self, revision: str, identity: str) -> bytes:
        if len(identity) != 64 or any(c not in "0123456789abcdef" for c in identity):
            raise KctxError("malformed", "invalid retained artifact identity")
        result = subprocess.run(
            ["git", "-C", str(self.repo), "show", f"{revision}:artifacts/{identity}"],
            capture_output=True,
            check=False,
        )
        if result.returncode:
            raise KctxError("not-found", "retained source artifact is missing")
        return result.stdout

    def publish(self, revision: str, predecessor: str | None) -> None:
        self.run("update-ref", RELEASE_REF, revision, predecessor or ("0" * len(revision)))
