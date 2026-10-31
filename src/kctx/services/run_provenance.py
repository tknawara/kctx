"""Count disjoint declared provenance roots, not repeated observation IDs.

Shared source origins, declared derivations and identical retained content
identify dependence. Distinct roots are a bounded accounting result, not a
claim to discover undeclared copying or prove causal independence.
"""

from collections.abc import Mapping
from typing import TypeAlias

from kctx.domain.ids import ContentDigest, ObservationId
from kctx.domain.records import Observation
from kctx.domain.vocabulary import ObservationStatus, ObservationSystem
from kctx.errors import KctxError

_Origin: TypeAlias = tuple[ObservationSystem, str] | ContentDigest


def independent_origins(
    observations: Mapping[ObservationId, Observation], evidence: tuple[ObservationId, ...]
) -> int:
    memo: dict[ObservationId, frozenset[_Origin]] = {}
    visiting: set[ObservationId] = set()

    def origins(identity: ObservationId) -> frozenset[_Origin]:
        if identity in memo:
            return memo[identity]
        if identity in visiting:
            raise KctxError("malformed", f"cyclic observation provenance at {identity}")
        observation = observations.get(identity)
        if observation is None:
            raise KctxError("incomplete", f"missing provenance observation {identity}")
        if observation.status is not ObservationStatus.OK:
            raise KctxError(
                "incomplete",
                f"evidence origin {identity} has status {observation.status.value}, not ok",
            )
        visiting.add(identity)
        roots: set[_Origin] = set()
        if observation.derived_from:
            for parent in observation.derived_from:
                roots.update(origins(parent))
        else:
            roots.add((observation.source.system, observation.source.locator))
        if observation.evidence is not None and observation.evidence.sha256 is not None:
            roots.add(observation.evidence.sha256)
        visiting.remove(identity)
        memo[identity] = frozenset(roots)
        return memo[identity]

    groups: list[set[_Origin]] = []
    for identity in evidence:
        combined = set(origins(identity))
        separate: list[set[_Origin]] = []
        for group in groups:
            if combined.intersection(group):
                combined.update(group)
            else:
                separate.append(group)
        # Every old group is disjoint from every other old group, so merging
        # the intersecting groups cannot create a missed transitive overlap.
        separate.append(combined)
        groups = separate
    return len(groups)


def evidence_dependencies(
    observations: Mapping[ObservationId, Observation], evidence: tuple[ObservationId, ...]
) -> frozenset[ObservationId]:
    dependencies: set[ObservationId] = set()
    pending = list(evidence)
    while pending:
        identity = pending.pop()
        if identity in dependencies:
            continue
        dependencies.add(identity)
        observation = observations.get(identity)
        if observation is not None:
            pending.extend(observation.derived_from)
    return frozenset(dependencies)
