import Kctx.Codec
import Kctx.Theorems

set_option autoImplicit false
set_option maxHeartbeats 2400000
set_option maxRecDepth 8192
namespace Kctx
open Lean

theorem decIdent_encIdent {kind : IdKind} (id : Ident kind) :
    decIdent (encIdent id) = .ok id := by
  simp [decIdent, encIdent, decStr, encStr, Json.getStr?, id.nonempty, bind, Except.bind, pure, Except.pure]

theorem encIdent_wire {kind : IdKind} (id : Ident kind) :
    encIdent id = Json.str id.val := rfl

theorem decOptionalIdent_encOptionalIdent {kind : IdKind} (id : Option (Ident kind)) :
    decOptionalIdent (encOptionalIdent id) = .ok id := by
  cases id with
  | none => rfl
  | some id =>
      simp [decOptionalIdent, encOptionalIdent, encIdent, decStr, encStr, Json.getStr?,
        id.nonempty, bind, Except.bind, pure, Except.pure]

theorem decList_encList {α : Type} (enc : α → Json) (dec : Json → Except String α)
    (xs : List α) (h : ∀ x ∈ xs, dec (enc x) = .ok x) :
    decList dec (encList enc xs) = .ok xs := by
  change decJsonList dec (xs.map enc) = .ok xs
  induction xs with
  | nil => rfl
  | cons x xs ih =>
      have hx := h x (by simp)
      have ht := ih (fun y hy => h y (by simp [hy]))
      simp only [List.map_cons, decJsonList, hx, ht, bind, Except.bind, pure, Except.pure]

theorem decScope_encScope (s : Scope) (h : scopeWf s = true) : decScope (encScope s) = .ok s := by
  change (do
    let project ← decIdent (encIdent s.project)
    let v : Scope := ⟨project, s.selector⟩
    if scopeWf v then pure v else throw "invalid_request") = .ok s
  rw [decIdent_encIdent]
  simp [h, bind, Except.bind, pure, Except.pure]

theorem decAtom_encAtom (a : Atom) (h : atomWf a = true) : decAtom (encAtom a) = .ok a := by
  have args := decList_encList encStr decStr a.args (fun _ _ => rfl)
  change (do
    let args ← decList decStr (encList encStr a.args)
    let v : Atom := ⟨a.subject, a.predicate, args⟩
    if atomWf v then pure v else throw "invalid_request") = .ok a
  rw [args]
  simp [h, bind, Except.bind, pure, Except.pure]

theorem decFormulaFuel_encFormula (f : Formula) (n : Nat)
    (wf : formulaWf f = true) (depth : formulaDepth f ≤ n) :
    decFormulaFuel n (encFormula f) = .ok f := by
  induction f generalizing n with
  | atom a =>
      cases n with
      | zero => simp [formulaDepth] at depth
      | succ n =>
          change (do let a ← decAtom (encAtom a); pure (Formula.atom a)) = .ok (.atom a)
          rw [decAtom_encAtom a wf]; rfl
  | truth =>
      cases n with
      | zero => simp [formulaDepth] at depth
      | succ n => rfl
  | and a b ia ib =>
      cases n with
      | zero => simp [formulaDepth] at depth
      | succ n =>
          have wa := (bool_and.mp wf).1
          have wb := (bool_and.mp wf).2
          have da : formulaDepth a ≤ n := by simp [formulaDepth] at depth; omega
          have db : formulaDepth b ≤ n := by simp [formulaDepth] at depth; omega
          change (do
            let a ← decFormulaFuel n (encFormula a)
            let b ← decFormulaFuel n (encFormula b)
            pure (Formula.and a b)) = .ok (.and a b)
          rw [ia n wa da, ib n wb db]; rfl
  | all id p =>
      cases n with
      | zero => simp [formulaDepth] at depth
      | succ n =>
          change (do let id ← decIdent (encIdent id); pure (Formula.all id p)) = .ok (.all id p)
          rw [decIdent_encIdent]; rfl
  | absent id =>
      cases n with
      | zero => simp [formulaDepth] at depth
      | succ n =>
          change (do let id ← decIdent (encIdent id); pure (Formula.absent id)) = .ok (.absent id)
          rw [decIdent_encIdent]; rfl
  | inventory id =>
      cases n with
      | zero => simp [formulaDepth] at depth
      | succ n =>
          change (do let id ← decIdent (encIdent id); pure (Formula.inventory id)) = .ok (.inventory id)
          rw [decIdent_encIdent]; rfl

theorem T02_formula_roundtrip (f : Formula) (wf : formulaWf f = true) (bound : formulaDepth f ≤ 256) :
    decFormula (encFormula f) = .ok f := by
  simp [decFormula, decFormulaFuel_encFormula f 256 wf bound, wf, bind, Except.bind, pure, Except.pure]

theorem T01_decoder_admission {j : Json} {k : KB} (h : decKB j = .ok k) : k.wellFormed = true :=
  decKB_wellFormed h

theorem decWitnessFuel_encWitness (w : Witness) (n : Nat)
    (wf : witnessWf w = true) (depth : witnessDepth w ≤ n) :
    decWitnessFuel n (encWitness w) = .ok w := by
  induction w generalizing n with
  | attest id =>
      cases n with
      | zero => simp [witnessDepth] at depth
      | succ n =>
          change (do let id ← decIdent (encIdent id); pure (Witness.attest id)) = .ok (.attest id)
          rw [decIdent_encIdent]; rfl
  | truth s =>
      cases n with
      | zero => simp [witnessDepth] at depth
      | succ n =>
          change (do let s ← decScope (encScope s); pure (Witness.truth s)) = .ok (.truth s)
          rw [decScope_encScope s wf]; rfl
  | and a b ia ib =>
      cases n with
      | zero => simp [witnessDepth] at depth
      | succ n =>
          have da : witnessDepth a ≤ n := by simp [witnessDepth] at depth; omega
          have db : witnessDepth b ≤ n := by simp [witnessDepth] at depth; omega
          change (do
            let a ← decWitnessFuel n (encWitness a)
            let b ← decWitnessFuel n (encWitness b)
            pure (Witness.and a b)) = .ok (.and a b)
          rw [ia n (bool_and.mp wf).1 da, ib n (bool_and.mp wf).2 db]; rfl
  | specialize s w ih =>
      cases n with
      | zero => simp [witnessDepth] at depth
      | succ n =>
          have dw : witnessDepth w ≤ n := by simp [witnessDepth] at depth; omega
          change (do
            let s ← decScope (encScope s)
            let w ← decWitnessFuel n (encWitness w)
            pure (Witness.specialize s w)) = .ok (.specialize s w)
          rw [decScope_encScope s (bool_and.mp wf).1, ih n (bool_and.mp wf).2 dw]; rfl
  | all id pred w ih =>
      cases n with
      | zero => simp [witnessDepth] at depth
      | succ n =>
          have dw : witnessDepth w ≤ n := by simp [witnessDepth] at depth; omega
          change (do
            let id ← decIdent (encIdent id)
            let w ← decWitnessFuel n (encWitness w)
            pure (Witness.all id pred w)) = .ok (.all id pred w)
          rw [decIdent_encIdent]
          simp only [bind, Except.bind, pure, Except.pure]
          rw [ih n (bool_and.mp wf).2 dw]
  | absent id w ih =>
      cases n with
      | zero => simp [witnessDepth] at depth
      | succ n =>
          have dw : witnessDepth w ≤ n := by simp [witnessDepth] at depth; omega
          change (do
            let id ← decIdent (encIdent id)
            let w ← decWitnessFuel n (encWitness w)
            pure (Witness.absent id w)) = .ok (.absent id w)
          rw [decIdent_encIdent]
          simp only [bind, Except.bind, pure, Except.pure]
          rw [ih n (bool_and.mp wf).2 dw]

theorem T02_witness_roundtrip (w : Witness) (wf : witnessWf w = true) (bound : witnessDepth w ≤ 256) :
    decWitness (encWitness w) = .ok w := by
  simp [decWitness, decWitnessFuel_encWitness w 256 wf bound, wf, bind, Except.bind, pure, Except.pure]

end Kctx
