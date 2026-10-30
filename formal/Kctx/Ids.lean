
set_option autoImplicit false

/-! Nominal identifiers.

Phantom-kinded wrappers: an `Ident IdKind.asset` and an `Ident IdKind.proposal`
with the same string are different types and cannot be interchanged. The
Python production core mirrors this with distinct frozen dataclasses. -/

namespace Kctx

inductive IdKind where
  | asset
  | claim
  | claimRev
  | citation
  | observation
  | proposal
  | investigation
  | signature
  | rule
  | operation
  | snapshot
deriving DecidableEq, Repr, Inhabited

structure Ident (k : IdKind) where
  val : String
deriving DecidableEq, Repr, Inhabited

instance {k : IdKind} : ToString (Ident k) where
  toString i := i.val

abbrev AssetId := Ident IdKind.asset
abbrev ClaimId := Ident IdKind.claim
abbrev ObservationId := Ident IdKind.observation
abbrev ProposalId := Ident IdKind.proposal

/-- A claim reference: logical id + immutable revision. The id alone cannot
identify the historical proposition (handover §4). -/
structure ClaimRef where
  id : ClaimId
  rev : String
deriving DecidableEq, Repr, Inhabited

/-! Core has no `deriving BEq` handler; these explicit instances are
field-wise (nominal ids compare by underlying string) or decide-based. -/
instance {k : IdKind} : BEq (Ident k) := ⟨fun a b => a.val == b.val⟩
instance : BEq IdKind := ⟨fun a b => decide (a = b)⟩
instance : BEq ClaimRef := ⟨fun a b => a.id == b.id && a.rev == b.rev⟩

end Kctx
