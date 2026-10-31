"""Application-boundary logging (handover 7.2).

The structlog implementation lives in kctx.graph.observability today; this
module is the stable seam every entry point and non-graph command imports,
so decoupling the implementation later touches one file. PORTING.md tracks
the move.
"""

from kctx.graph.observability import (  # noqa: F401
    init_logging,
    span,
    get_logger,
    run_logged,
)
