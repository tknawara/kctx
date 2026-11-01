"""Static consumer contract: nominal identities survive service boundaries."""

from pathlib import Path

from kctx.domain.ids import AssetId, ClaimId, ClaimRevision, ContextId, ObservationId, ProposalId, RunId
from kctx.domain.vocabulary import AssetKind, RelationshipType
from kctx.semantics.model import ClaimRef, Context
from kctx.semantics.portfolio import query_context_allowed
from kctx.semantics.workflow_models import NamedContext, PortfolioState
from kctx.services import inventory, proposals, runs


def valid_consumer(root: Path) -> ClaimRef:
    asset = inventory.asset_add(root, id=AssetId("same"), kind=AssetKind.SERVICE, name="same")
    inventory.rel_add(root, type=RelationshipType.DEPENDS_ON, from_=asset.id, to=AssetId("other"))
    proposals.load(root, ProposalId("same"))
    runs.get_observation(root, RunId("run1"), ObservationId("obs1"))
    return ClaimRef(ClaimId("same"), ClaimRevision("r1"))


def valid_context_consumer(state: PortfolioState, context: Context) -> bool:
    named = NamedContext(ContextId("review"), context)
    return query_context_allowed(state, named.id, context)
