"""Development reference dispatcher for workflow schema 3, using production twins.

Trusted capability arguments come from an authenticated adapter or a separately
constructed conformance environment, never from fields of an ordinary request.
"""

from kctx.domain.ids import ContextId
from kctx.errors import KctxError
from kctx.semantics import model as M
from kctx.semantics import workflow_models as W
from kctx.semantics import workflow_wire as C
from kctx.semantics.design_workflow import (
    bind_implementation,
    design_candidate_valid,
    design_transition,
    reopen_design,
)
from kctx.semantics.portfolio import (
    apply_portfolio,
    apply_portfolio_selection,
    assess_portfolio,
    portfolio_plan_valid,
    portfolio_selection_valid,
    portfolio_state_valid,
    query_context_allowed,
)
from kctx.semantics.wire import (
    dec_context,
    dec_ref,
    enc_assessment,
    items,
    nat,
    nonempty,
    obj,
    text,
)

_BASE = "schema_version semantic_version id op"


def handle(
    request: dict[str, object],
    trusted_approvals: tuple[W.VerifiedPortfolioApproval, ...] = (),
    trusted_selections: tuple[W.VerifiedPortfolioSelectionApproval, ...] = (),
    retained: tuple[W.PortfolioState, ...] = (),
) -> object:
    if (
        nat(request["schema_version"]) != W.WORKFLOW_SCHEMA_VERSION
        or request["semantic_version"] != M.SEMANTIC_VERSION
    ):
        raise ValueError("invalid_request")
    nonempty(request["id"])
    operation = text(request["op"])
    if operation in ("semantic_version", "workflow_version"):
        obj(request, _BASE)
        return M.SEMANTIC_VERSION if operation == "semantic_version" else W.WORKFLOW_SCHEMA_VERSION
    if operation == "portfolio_state_valid":
        obj(request, _BASE + " state")
        return portfolio_state_valid(C.dec_portfolio_state(request["state"]))
    if operation == "portfolio_valid":
        obj(request, _BASE + " state plan")
        return portfolio_plan_valid(
            C.dec_portfolio_state(request["state"]), C.dec_portfolio_plan(request["plan"])
        )
    if operation == "portfolio_admit":
        obj(request, _BASE + " state journal plan")
        return C.enc_portfolio_result(
            apply_portfolio(
                C.dec_portfolio_state(request["state"]),
                items(request["journal"], C.dec_portfolio_journal_entry),
                C.dec_portfolio_plan(request["plan"]),
                trusted_approvals=trusted_approvals,
            )
        )
    if operation in ("portfolio_query_allowed", "portfolio_assess"):
        obj(
            request,
            _BASE
            + " state context_id context"
            + (" claim" if operation == "portfolio_assess" else ""),
        )
        state = C.dec_portfolio_state(request["state"])
        context_id = ContextId(text(request["context_id"]))
        context = dec_context(request["context"])
        if operation == "portfolio_query_allowed":
            return query_context_allowed(state, context_id, context)
        assessment = assess_portfolio(state, context_id, context, dec_ref(request["claim"]))
        return None if assessment is None else enc_assessment(assessment)
    if operation == "portfolio_selection_valid":
        obj(request, _BASE + " state plan")
        return portfolio_selection_valid(
            C.dec_portfolio_state(request["state"]),
            C.dec_portfolio_selection_plan(request["plan"]),
            retained=retained,
        )
    if operation == "portfolio_select":
        obj(request, _BASE + " state journal plan")
        return C.enc_portfolio_selection_result(
            apply_portfolio_selection(
                C.dec_portfolio_state(request["state"]),
                items(request["journal"], C.dec_portfolio_selection_journal_entry),
                C.dec_portfolio_selection_plan(request["plan"]),
                trusted_approvals=trusted_selections,
                retained=retained,
            )
        )
    if operation in ("design_valid", "design_transition"):
        obj(request, _BASE + " proposal target_status now")
        decision = design_candidate_valid if operation == "design_valid" else design_transition
        return decision(
            C.dec_design_proposal(request["proposal"]),
            M.AuthoredStatus(text(request["target_status"])),
            nat(request["now"]),
        )
    if operation == "design_bind":
        obj(request, _BASE + " proposal command now")
        bound = bind_implementation(
            C.dec_design_proposal(request["proposal"]),
            C.dec_design_binding_command(request["command"]),
            nat(request["now"]),
        )
        return None if bound is None else C.enc_design_proposal(bound)
    if operation == "design_reopen":
        obj(request, _BASE + " proposal command")
        reopened = reopen_design(
            C.dec_design_proposal(request["proposal"]),
            C.dec_design_reopen_command(request["command"]),
        )
        return None if reopened is None else C.enc_design_proposal(reopened)
    raise ValueError("invalid_request")


def evaluate_request(
    request: dict[str, object],
    *,
    trusted_approvals: tuple[W.VerifiedPortfolioApproval, ...] = (),
    trusted_selections: tuple[W.VerifiedPortfolioSelectionApproval, ...] = (),
    retained: tuple[W.PortfolioState, ...] = (),
) -> dict[str, object]:
    ident = request.get("id", "")
    try:
        result = handle(request, trusted_approvals, trusted_selections, retained)
        return {"id": ident, "ok": True, "result": result}
    except (ValueError, KeyError, TypeError, RecursionError, KctxError):
        try:
            safe_id = text(ident)
        except ValueError:
            safe_id = ""
        return {"id": safe_id, "ok": False, "error": "invalid_request"}
