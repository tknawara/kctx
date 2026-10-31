/-! # kctx knowledge calculus — root

Bounded first calculus per `docs/kctx/handover.md` §4–§5: claims, evidence,
derivations, freshness, corrections, and workflow transitions. Proved
generically over every well-formed KB; no corpus-specific facts. Concrete
data appears only in the `NonVacuity` examples (kernel-checked by `decide`). -/

import Kctx.Ids
import Kctx.Time
import Kctx.Model
import Kctx.WellFormed
import Kctx.Semantics
import Kctx.Checker
import Kctx.Workflow
import Kctx.Codec
import Kctx.Theorems
import Kctx.Theorems2
