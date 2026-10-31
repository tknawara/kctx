import Kctx.Model
open Kctx
def rejectedSnapshot (context : Context) (revision : SourceRevision) : Context := { context with snapshot := revision }
