"""Deliberate production-decision mutants killed by independent golden fixtures.

No source-text assertions: each mutation replaces an executed production leaf or
workflow guard, then invokes the same versioned public boundary as services.
"""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
from unittest.mock import patch
import json
from pathlib import Path

from kctx.domain.ids import ContextId
from kctx.semantics import checker, design_workflow, model as M, portfolio, wire, workflow, workflow_reference
from kctx.semantics import workflow_models as W
from scripts.semantic_cases import reviewed_cases


def mutation_campaign() -> dict[str, object]:
    fixtures = {str(case["id"]): case for case in reviewed_cases()}
    for path in sorted((Path(__file__).resolve().parents[1] / "tests/conformance").glob("workflow-v3*.jsonl")):
        fixtures.update((str(case["id"]), case) for case in (
            json.loads(line) for line in path.read_text().splitlines() if line.strip()
        ))
    original_fresh = checker.assess_fresh
    original_assess = checker.assess
    original_union = checker.dependencies_union

    def ttl_boundary(ttl: M.Ttl, observed_at: int, now: int) -> M.Freshness:
        if ttl.tag is M.TtlTag.EXPIRE_AFTER and ttl.secs is not None and now == observed_at + ttl.secs:
            return M.Freshness.STALE
        return original_fresh(ttl, observed_at, now)

    def unknown_fresh(ttl: M.Ttl, observed_at: int, now: int) -> M.Freshness:
        result = original_fresh(ttl, observed_at, now)
        return M.Freshness.FRESH if result is M.Freshness.UNKNOWN else result

    def dropped_dependency(left: tuple[M.Dependency, ...], right: tuple[M.Dependency, ...]) -> tuple[M.Dependency, ...]:
        return tuple(d for d in original_union(left, right) if not isinstance(d, M.ObservationDependency))

    def erased_dispute(kb: M.KB, context: M.Context, ref: M.ClaimRef) -> M.Assessment:
        return original_assess(replace(kb, corrections=tuple(c for c in kb.corrections if c.kind is not M.CorrectionKind.DISPUTE)), context, ref)

    def historical_latest(proposal: M.AuthoredProposal, definition: M.AuthoredGateDefinition, now: int) -> bool:
        result = next((result for result in reversed(proposal.gate_results)
                       if result.definition == definition and result.target_revision == proposal.target_revision
                       and result.checker == definition.checker), None)
        return result is not None and result.result is M.GateOutcome.PASS and result.observed_at <= now <= result.expires_at

    def swapped_target(target: M.Scope, source: M.Scope) -> bool:
        return True

    def skipped_gate(kb: M.KB, context: M.Context, proposal: M.Proposal, target: M.ProposalStatus) -> bool:
        return proposal.status is M.ProposalStatus.APPROVED and target is M.ProposalStatus.APPLIED

    def skipped_assignment(kb: M.KB, contexts: tuple[W.NamedContext, ...], assignment: W.ClaimAssignment) -> bool:
        return True

    def borrowed_context(state: W.PortfolioState, identity: ContextId, context: M.Context) -> bool:
        return True

    def implicit_retirement(before: tuple[W.NamedContext, ...], after: tuple[W.NamedContext, ...], retired: tuple[ContextId, ...]) -> bool:
        return True

    def skipped_implementation(proposal: W.DesignProposal, now: int) -> bool:
        return True

    mutations: tuple[tuple[str, str, object, str, str], ...] = (
        ("ttl-boundary", "inclusive-evidence-ttl", ttl_boundary, "checker", "assess_fresh"),
        ("dropped-dependency", "retained-footprint-complete", dropped_dependency, "checker", "dependencies_union"),
        ("unknown-fresh", "unknown-ttl-not-fresh", unknown_fresh, "checker", "assess_fresh"),
        ("swapped-target", "target-scope-must-apply", swapped_target, "checker", "narrower"),
        ("skipped-gate", "skipped-gate-not-applied", skipped_gate, "wire", "transition"),
        ("erased-dispute", "dispute-preserves-support", erased_dispute, "wire", "assess"),
        ("historical-latest-selection", "authored-historical-prefilter", historical_latest, "workflow", "authored_gate_passes"),
        ("unsupported-portfolio-assignment", "v3-unsupported-added-claim", skipped_assignment, "portfolio", "assignment_valid"),
        ("borrowed-context-authorization", "v3-cannot-borrow-target-authority", borrowed_context, "workflow_reference", "query_context_allowed"),
        ("implicit-context-retirement", "v3-implicit-context-retirement-refused", implicit_retirement, "portfolio", "context_evolution_valid"),
        ("unbound-implementation", "v3-finalized-requires-implementation-binding", skipped_implementation, "design_workflow", "implementation_bound"),
    )
    modules = {"checker": checker, "wire": wire, "workflow": workflow, "portfolio": portfolio, "workflow_reference": workflow_reference, "design_workflow": design_workflow}
    reports: list[dict[str, object]] = []
    for name, fixture_id, replacement, module, attribute in mutations:
        fixture = fixtures[fixture_id]
        request = {key: value for key, value in fixture.items() if key not in ("expected", "expected_response", "trusted_environment", "category")}
        expected = {"id": fixture_id, "ok": True, "result": fixture["expected"]}
        baseline = wire.evaluate_request(request)
        with ExitStack() as stack:
            stack.enter_context(patch.object(modules[module], attribute, replacement))
            mutated = wire.evaluate_request(request)
        killed = baseline == expected and mutated != expected and mutated.get("ok") is True
        reports.append({"mutation": name, "fixture": fixture_id, "baseline": baseline,
                        "mutated": mutated, "killed": killed})
    return {"result": "pass" if all(report["killed"] for report in reports) else "fail",
            "total": len(reports), "killed": sum(report["killed"] is True for report in reports), "mutants": reports}
