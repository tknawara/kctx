import Kctx.Model
open Kctx
def rejectedClaimLookup (kb : KB) (id : ClaimId) : Option Observation := observationAt kb id
