import Kctx.Ids

set_option autoImplicit false

/-! Explicit time and freshness.

Instants are integer epoch seconds supplied by the evaluation context — never
read from a clock inside the core. Freshness is an assessment relative to a
context, not a stored property. (Types are plain `Int` — no abbreviations —
because `omega` in Lean 4.21 cannot see through `abbrev`-typed atoms.)

Clock convention (handover §4.3): with duration `ttl`, recency holds iff
`observedAt <= now <= observedAt + ttl` (inclusive boundary, preserving the
existing `is_past_ttl` behavior). Future observations are `unknown`, never
`fresh`. A missing TTL policy is never an implicit freshness proof. -/

namespace Kctx

inductive TtlPolicy where
  | expireAfter (secs : Int)
  | noExpiry
  | missing
deriving DecidableEq, Repr, Inhabited

inductive Fresh where
  | fresh
  | stale
  | unknown
deriving DecidableEq, Repr, Inhabited

instance : BEq TtlPolicy := ⟨fun a b => decide (a = b)⟩
instance : BEq Fresh := ⟨fun a b => decide (a = b)⟩

/-- Declared recency condition (Prop twin of the executable assessment). -/
def FreshAt (o : TtlPolicy) (observedAt now : Int) : Prop :=
  observedAt ≤ now ∧ match o with
    | .expireAfter s => now ≤ observedAt + s
    | .noExpiry => True
    | .missing => False

/-- Executable freshness assessment. -/
def assessFresh (o : TtlPolicy) (observedAt now : Int) : Fresh :=
  if observedAt ≤ now then
    match o with
    | .missing => .unknown
    | .noExpiry => .fresh
    | .expireAfter s => if now ≤ observedAt + s then .fresh else .stale
  else .unknown

theorem assessFresh_iff_fresh_expire (s : Int) (observedAt now : Int) :
    assessFresh (.expireAfter s) observedAt now = Fresh.fresh ↔
      (observedAt ≤ now ∧ now ≤ observedAt + s) := by
  simp only [assessFresh]
  by_cases h1 : observedAt ≤ now
  · rw [if_pos h1]
    by_cases h2 : now ≤ observedAt + s
    · rw [if_pos h2]; simp [h1, h2]
    · rw [if_neg h2]; simp [h2]
  · rw [if_neg h1]; simp [h1]

theorem assessFresh_fresh_iff {o : TtlPolicy} {observedAt now : Int} :
    assessFresh o observedAt now = Fresh.fresh ↔ FreshAt o observedAt now := by
  cases o with
  | expireAfter s => simp [FreshAt, assessFresh_iff_fresh_expire]
  | noExpiry =>
    simp only [assessFresh, FreshAt]
    by_cases h1 : observedAt ≤ now
    · rw [if_pos h1]; simp [h1]
    · rw [if_neg h1]; simp [h1]
  | missing =>
    simp only [assessFresh, FreshAt]
    by_cases h1 : observedAt ≤ now
    · rw [if_pos h1]; simp
    · rw [if_neg h1]; simp

/-- T11 (core): with fixed inputs and no new validation, advancing the
evaluation time can never restore expired recency. -/
theorem assessFresh_stale_mono {o : TtlPolicy} {observedAt now now' : Int}
    (h : assessFresh o observedAt now = Fresh.stale) (hle : now ≤ now') :
    assessFresh o observedAt now' = Fresh.stale := by
  cases o with
  | expireAfter s =>
    have h1 : observedAt ≤ now := by
      by_cases hc : observedAt ≤ now
      · exact hc
      · simp only [assessFresh] at h
        rw [if_neg hc] at h
        exact absurd h (by simp)
    have h2 : ¬ (now ≤ observedAt + s) := by
      intro hp
      have hf := (assessFresh_iff_fresh_expire s observedAt now).mpr ⟨h1, hp⟩
      rw [hf] at h
      exact absurd h (by simp)
    simp only [assessFresh]
    rw [if_pos (show observedAt ≤ now' by omega)]
    rw [if_neg (show ¬ (now' ≤ observedAt + s) by omega)]
  | noExpiry =>
    simp only [assessFresh] at h
    split at h <;> exact absurd h (by simp)
  | missing =>
    simp only [assessFresh] at h
    split at h <;> exact absurd h (by simp)

/-- Future timestamps never assess as fresh (bounded-skew policy: reject). -/
theorem assessFresh_future_not_fresh {o : TtlPolicy} {observedAt now : Int}
    (h : now < observedAt) : assessFresh o observedAt now = Fresh.unknown := by
  cases o with
  | expireAfter s =>
    simp only [assessFresh]
    split
    · next hle => exfalso; omega
    · rfl
  | noExpiry =>
    simp only [assessFresh]
    split
    · next hle => exfalso; omega
    · rfl
  | missing => simp only [assessFresh]; split <;> rfl

end Kctx
