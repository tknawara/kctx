import Kctx.Model

set_option autoImplicit false
namespace Kctx

def token (s : String) : Bool :=
  match s.toList with
  | [] => false
  | c :: cs => c.isAlphanum && cs.all (fun c => c.isAlphanum || ['_', '.', ':', '-'].contains c)

def scopeWf (s : Scope) : Bool := s.project.val != ""
def atomWf (a : Atom) : Bool := a.subject != "" && a.predicate != ""
def formulaWf : Formula → Bool
  | .atom a => atomWf a
  | .truth => true
  | .and a b => formulaWf a && formulaWf b
  | .all e p => token e.val && p != ""
  | .absent e | .inventory e => token e.val
def statementWf (s : Statement) : Bool := scopeWf s.scope && formulaWf s.formula &&
  (s.polarity == .positive || match s.formula with | .atom _ => true | _ => false)
def refWf (r : Ref) : Bool := token r.id.val && token r.revision.val
def observationWf (o : Observation) : Bool :=
  token o.id.val && o.source.val != "" && o.revision.val != "" && o.content.val != ""
def ttlWf : TtlPolicy → Bool
  | .expireAfter seconds => decide (0 ≤ seconds)
  | .noExpiry | .missing => true

def contextWf (e : Context) : Bool :=
  token e.snapshot.val && e.semanticVersion == semanticVersion && e.ruleset.val == "core-2" &&
  e.checker.val == "kctx-2" && token e.policy.id.val && scopeWf e.target && e.intendedUse != "" &&
  ttlWf e.policy.ttl &&
  e.policy.authorizedActors.all (fun actor => actor.val != "") &&
  e.policy.authorizedActors.eraseDups.length == e.policy.authorizedActors.length &&
  e.sources.all (fun s => s.source.val != "" && s.revision.val != "" && s.content.val != "") &&
  (e.sources.map (·.source)).eraseDups.length == e.sources.length
def contextValid (k : KB) (e : Context) : Bool := e.snapshot == k.snapshot && contextWf e
def unique {α : Type} [BEq α] (xs : List α) : Bool := xs.eraseDups.length == xs.length

def formulaDepth : Formula → Nat
  | .and a b => 1 + max (formulaDepth a) (formulaDepth b)
  | _ => 1
def witnessDepth : Witness → Nat
  | .and a b => 1 + max (witnessDepth a) (witnessDepth b)
  | .specialize _ w | .all _ _ w | .absent _ w => 1 + witnessDepth w
  | _ => 1
def witnessWf : Witness → Bool
  | .attest a => token a.val
  | .truth s => scopeWf s
  | .and a b => witnessWf a && witnessWf b
  | .specialize s w => scopeWf s && witnessWf w
  | .all e p w => token e.val && p != "" && witnessWf w
  | .absent e w => token e.val && witnessWf w

def formulaRefs (k : KB) : Formula → Bool
  | .atom _ | .truth => true
  | .and a b => formulaRefs k a && formulaRefs k b
  | .all e _ | .absent e | .inventory e => (enumerationAt k e).isSome

def witnessRefs (k : KB) : Witness → Bool
  | .attest a => (attestationAt k a).isSome
  | .truth s => scopeWf s
  | .and a b => witnessRefs k a && witnessRefs k b
  | .specialize s w => scopeWf s && witnessRefs k w
  | .all e p w => (enumerationAt k e).isSome && p != "" && witnessRefs k w
  | .absent e w => (enumerationAt k e).isSome && witnessRefs k w

/-- Bounded graph search; a simple cycle has length at most the edge count. -/
def reaches (edges : List (Ref × Ref)) : Nat → Ref → Ref → Bool
  | 0, _, _ => false
  | n + 1, a, b => edges.any (fun edge => edge.1 == a && (edge.2 == b || reaches edges n edge.2 b))

def supersessionEdges (k : KB) : List (Ref × Ref) :=
  k.corrections.filterMap (fun c => if c.kind == .supersede then c.replacement.map (c.target, ·) else none)

def dependencyWf (k : KB) : Dependency → Bool
  | .observation o => k.observations.contains o
  | .claim c => k.claims.contains c
  | .attestation a => k.attestations.contains a
  | .enumeration e => k.enumerations.contains e
  | .corrections r cs => (claimAt k r).isSome && cs.all (fun c => c.target == r && k.corrections.contains c)
  | .context e => contextWf e && e.now == 0

def KB.wellFormed (k : KB) : Bool :=
  token k.snapshot.val &&
  unique (k.observations.map (·.id)) && unique (k.claims.map Claim.ref) &&
  unique (k.attestations.map (·.id)) && unique (k.enumerations.map (·.id)) &&
  unique (k.derivations.map (·.id)) && unique (k.corrections.map (·.id)) &&
  unique (k.receipts.map (·.id)) &&
  k.observations.all observationWf &&
  k.claims.all (fun c => refWf c.ref && statementWf c.statement && formulaRefs k c.statement.formula) &&
  k.attestations.all (fun a => token a.id.val && a.authority.val != "" &&
    (observationAt k a.observation).isSome &&
    match claimAt k a.claim, a.statement.formula with
    | some c, .atom _ => c.statement == a.statement
    | some c, .inventory id => c.statement == a.statement && a.statement.polarity == .positive &&
        match enumerationAt k id with
        | some z => a.observation == z.observation && a.statement.scope == z.scope
        | none => false
    | _, _ => false) &&
  k.enumerations.all (fun e => token e.id.val && e.source.val != "" && e.revision.val != "" &&
    e.query != "" && e.method != "" && scopeWf e.scope && e.members == e.universe &&
    unique e.members && e.members.all (· != "") &&
    match observationAt k e.observation with
    | some o => o.source == e.source && o.revision == e.revision
    | none => false) &&
  k.derivations.all (fun d => token d.id.val && (claimAt k d.claim).isSome && witnessRefs k d.witness) &&
  k.corrections.all (fun c => token c.id.val && (claimAt k c.target).isSome &&
    match c.kind, c.replacement with
    | .supersede, some r => (claimAt k r).isSome
    | .supersede, none => false
    | _, none => true
    | _, some _ => false) &&
  !(supersessionEdges k).any (fun edge => reaches (supersessionEdges k) k.corrections.length edge.2 edge.1) &&
  k.receipts.all (fun r => token r.id.val && (claimAt k r.claim).isSome && contextWf r.context &&
    witnessRefs k r.witness && r.dependencies.all (dependencyWf k))

/-- The public boundary returns admitted structure, never an unchecked record list. -/
def admitKB (k : KB) : Option KB := if k.wellFormed then some k else none

theorem admitKB_sound {k admitted : KB} (h : admitKB k = some admitted) :
    admitted.wellFormed = true := by
  simp only [admitKB] at h
  split at h
  · cases h; assumption
  · contradiction

theorem admitKB_complete {k : KB} (h : k.wellFormed = true) : admitKB k = some k := by
  simp [admitKB, h]

end Kctx
