set_option autoImplicit false

/-! Distinct nominal identifier namespaces. Wire text is accessed only explicitly
through `.val`; there are no coercions to/from String or between namespaces. -/
namespace Kctx

inductive IdKind where
  | asset | project | claim | claimRev | citation | observation | attestation
  | enumeration | derivation | correction | receipt | proposal | proposalRev
  | investigation | signature | rule | ruleVersion | operation | snapshot
  | policy | checker | source | sourceRev | content | actor | gate | targetRev | context
  deriving DecidableEq, Repr, Inhabited

structure Ident (kind : IdKind) where
  val : String
  nonempty : val ≠ ""
  deriving DecidableEq, Repr

instance {kind : IdKind} : Inhabited (Ident kind) :=
  ⟨⟨"_", by decide⟩⟩

instance {kind : IdKind} : BEq (Ident kind) := ⟨fun a b => decide (a = b)⟩
instance {kind : IdKind} : LawfulBEq (Ident kind) where
  eq_of_beq := of_decide_eq_true
  rfl := by intro a; exact decide_eq_true rfl

abbrev AssetId := Ident .asset
abbrev ProjectId := Ident .project
abbrev ClaimId := Ident .claim
abbrev ClaimRevision := Ident .claimRev
abbrev CitationId := Ident .citation
abbrev ObservationId := Ident .observation
abbrev AttestationId := Ident .attestation
abbrev EnumerationId := Ident .enumeration
abbrev DerivationId := Ident .derivation
abbrev CorrectionId := Ident .correction
abbrev ReceiptId := Ident .receipt
abbrev ProposalId := Ident .proposal
abbrev ProposalRevision := Ident .proposalRev
abbrev InvestigationId := Ident .investigation
abbrev SignatureId := Ident .signature
abbrev RuleId := Ident .rule
abbrev RuleVersion := Ident .ruleVersion
abbrev OperationId := Ident .operation
abbrev SnapshotId := Ident .snapshot
abbrev PolicyId := Ident .policy
abbrev CheckerId := Ident .checker
abbrev SourceId := Ident .source
abbrev SourceRevision := Ident .sourceRev
abbrev ContentId := Ident .content
abbrev ActorId := Ident .actor
abbrev GateId := Ident .gate
abbrev TargetRevision := Ident .targetRev
abbrev ContextId := Ident .context

/-- A generic lookup never erases the key's namespace. -/
def lookup {kind : IdKind} {α : Type} (key : α → Ident kind)
    (records : List α) (id : Ident kind) : Option α :=
  records.find? (fun record => key record == id)

end Kctx
