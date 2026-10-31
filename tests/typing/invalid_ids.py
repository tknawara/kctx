"""Intentionally invalid consumer code; every marked line must be rejected."""

from pathlib import Path

from kctx.domain.ids import AssetId, ClaimId, ClaimRevision, ProposalId, RunId
from kctx.domain.vocabulary import AssetKind, Lifecycle, ProposalStatus, RelationshipType
from kctx.semantics.model import ClaimRef
from kctx.services import inventory, proposals, runs


def invalid_consumer(root: Path) -> None:
    proposals.load(root, ClaimId("same"))  # expect-error
    proposals.load(root, AssetId("same"))  # expect-error
    proposals.load(root, "same")  # expect-error
    inventory.asset_add(root, id=ProposalId("same"), kind=AssetKind.SERVICE, name="same")  # expect-error
    inventory.rel_add(root, type=RelationshipType.DEPENDS_ON, from_=ClaimId("same"), to=AssetId("other"))  # expect-error
    runs.get_observation(root, RunId("run1"), ProposalId("same"))  # expect-error
    ClaimRef(ProposalId("same"), ClaimRevision("r1"))  # expect-error
    ClaimRef(ClaimId("same"), "r1")  # expect-error
    inventory.asset_add(root, kind=AssetKind.SERVICE, name="same", lifecycle=ProposalStatus.DRAFT)  # expect-error
    inventory.asset_add(root, kind=Lifecycle.ACTIVE, name="same")  # expect-error
