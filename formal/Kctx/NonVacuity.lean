import Kctx.Theorems2

set_option autoImplicit false
namespace Kctx.NonVacuity

def scope : Scope := ⟨⟨"project", by decide⟩, ""⟩
def atom : Atom := ⟨"item", "checked", []⟩
def statement : Statement := ⟨.atom atom, scope, .positive⟩
def claim : Claim := ⟨⟨"claim", by decide⟩, ⟨"r1", by decide⟩, statement⟩
def unsupported : Claim := ⟨⟨"unsupported", by decide⟩, ⟨"r1", by decide⟩, ⟨.atom ⟨"other", "checked", []⟩, scope, .positive⟩⟩
def observation : Observation := ⟨⟨"obs", by decide⟩, ⟨"source", by decide⟩, ⟨"r1", by decide⟩, ⟨"retained-bytes", by decide⟩, 10, .ok⟩
def inventory : Observation := ⟨⟨"inventory", by decide⟩, ⟨"index", by decide⟩, ⟨"r1", by decide⟩, ⟨"inventory:4:item", by decide⟩, 10, .ok⟩
def emptyInventory : Observation := ⟨⟨"empty", by decide⟩, ⟨"empty-index", by decide⟩, ⟨"r1", by decide⟩, ⟨"inventory:", by decide⟩, 10, .ok⟩
def attestation : Attestation := ⟨⟨"attestation", by decide⟩, claim.ref, observation.id, statement, ⟨"reviewer", by decide⟩⟩
def enumeration : Enumeration := ⟨⟨"domain", by decide⟩, ⟨"index", by decide⟩, ⟨"r1", by decide⟩, "declared-query", scope, inventory.id, ["item"], ["item"], "retained-inventory"⟩
def emptyEnumeration : Enumeration := ⟨⟨"empty-domain", by decide⟩, ⟨"empty-index", by decide⟩, ⟨"r1", by decide⟩, "empty-query", scope, emptyInventory.id, [], [], "retained-inventory"⟩
def inventoryClaim : Claim := ⟨⟨"inventory-claim", by decide⟩, ⟨"r1", by decide⟩, ⟨.inventory ⟨"domain", by decide⟩, scope, .positive⟩⟩
def emptyClaim : Claim := ⟨⟨"empty-claim", by decide⟩, ⟨"r1", by decide⟩, ⟨.inventory ⟨"empty-domain", by decide⟩, scope, .positive⟩⟩
def inventoryAttest : Attestation := ⟨⟨"inventory-cert", by decide⟩, inventoryClaim.ref, inventory.id, inventoryClaim.statement, ⟨"enumerator", by decide⟩⟩
def emptyAttest : Attestation := ⟨⟨"empty-cert", by decide⟩, emptyClaim.ref, emptyInventory.id, emptyClaim.statement, ⟨"enumerator", by decide⟩⟩
def kb : KB := ⟨⟨"snapshot", by decide⟩, [observation, inventory, emptyInventory], [claim, unsupported, inventoryClaim, emptyClaim],
  [attestation, inventoryAttest, emptyAttest], [enumeration, emptyEnumeration], [⟨⟨"derivation", by decide⟩, claim.ref, .attest attestation.id⟩], [], []⟩
def context : Context := ⟨⟨"snapshot", by decide⟩, "2.0.0", ⟨"core-2", by decide⟩, ⟨"kctx-2", by decide⟩,
  ⟨⟨"policy", by decide⟩, true, false, true, .expireAfter 20, [⟨"reviewer", by decide⟩]⟩, 20, scope, "review",
  [⟨⟨"source", by decide⟩, ⟨"r1", by decide⟩, ⟨"retained-bytes", by decide⟩⟩, ⟨⟨"index", by decide⟩, ⟨"r1", by decide⟩, ⟨"inventory:4:item", by decide⟩⟩, ⟨⟨"empty-index", by decide⟩, ⟨"r1", by decide⟩, ⟨"inventory:", by decide⟩⟩]⟩

theorem inhabited_wellFormed : kb.wellFormed = true := by decide
theorem leaf_nonvacuous : (checkWitness kb context (.attest ⟨"attestation", by decide⟩)).isSome = true := by decide
theorem truth_nonvacuous : (checkWitness kb context (.truth scope)).isSome = true := by decide
theorem conjunction_nonvacuous : (checkWitness kb context (.and (.attest ⟨"attestation", by decide⟩) (.truth scope))).isSome = true := by decide
theorem specialization_nonvacuous : (checkWitness kb context (.specialize ⟨⟨"project", by decide⟩, "staging"⟩ (.attest ⟨"attestation", by decide⟩))).isSome = true := by decide
theorem coverage_nonvacuous : (checkWitness kb context (.all ⟨"domain", by decide⟩ "checked"
  (.and (.attest ⟨"inventory-cert", by decide⟩) (.and (.attest ⟨"attestation", by decide⟩) (.truth scope))))).isSome = true := by decide
theorem absence_nonvacuous : (checkWitness kb context (.absent ⟨"empty-domain", by decide⟩ (.attest ⟨"empty-cert", by decide⟩))).isSome = true := by decide
theorem unsupported_rejected : supported kb context unsupported.ref .positive = false := by decide
theorem usable_nonvacuous : usableFor kb context claim.ref = true := by decide
theorem false_coverage_rejected : checkWitness kb context (.all ⟨"domain", by decide⟩ "checked" (.truth scope)) = none := by decide
theorem uncertified_coverage_rejected : checkWitness kb context (.all ⟨"domain", by decide⟩ "checked" (.and (.attest ⟨"attestation", by decide⟩) (.truth scope))) = none := by decide
theorem scope_widening_rejected : checkWitness kb context (.specialize ⟨⟨"other-project", by decide⟩, ""⟩ (.attest ⟨"attestation", by decide⟩)) = none := by decide

def falseKB : KB := { kb with attestations := [], derivations := [] }
theorem falseKB_wellFormed : falseKB.wellFormed = true := by decide
theorem falseKB_evidence_sound : EvidenceSound falseInterpretation falseKB context := by
  intro id a o ha
  simp [attestationAt, lookup, falseKB] at ha

theorem falseKB_no_arbitrary_support (w : Witness) (r : Checked)
    (h : r.statement = unsupported.statement) : checkWitness falseKB context w ≠ some r :=
  unsupported_atom_impossible falseKB_evidence_sound w r ⟨"other", "checked", []⟩ scope .positive h

/-- Independent discovery semantics can disagree with a forged empty inventory. -/
def nonemptyDomain : Interpretation := ⟨fun _ _ _ => False, fun _ _ _ _ _ => ["real-member"]⟩
theorem false_absence_impossible {k : KB} {e : Context} (sound : EvidenceSound nonemptyDomain k e)
    {w : Witness} {r : Checked} {id : EnumerationId} {s : Scope}
    (hr : r.statement = ⟨.absent id, s, .positive⟩) : checkWitness k e w ≠ some r := by
  intro accepted
  have truth := T05_derives_sound sound (T04_checker_sound accepted)
  rw [hr] at truth
  rcases truth with ⟨_, z, _, empty⟩
  simp [domainMembers, nonemptyDomain] at empty

theorem structural_completion_empty : conclude ⟨"examined inputs", "bounded scope", []⟩ = true := by decide
theorem structural_completion_unknown : conclude ⟨"examined inputs", "bounded scope", [⟨"unknown outcome", .unk⟩]⟩ = true := by decide

/-- Explicit no-expiry remains usable long after a finite TTL, without disabling
the mandatory freshness gate. Missing policy stays unknown and unusable. -/
theorem no_expiry_policy_usable :
    usableFor kb { context with now := 10000, policy := { context.policy with ttl := .noExpiry } } claim.ref = true := by
  decide

theorem missing_policy_not_usable :
    usableFor kb { context with now := 10000, policy := { context.policy with ttl := .missing } } claim.ref = false := by
  decide

theorem no_expiry_future_unknown : assessFresh .noExpiry 11 10 = .unknown := by decide

end Kctx.NonVacuity
