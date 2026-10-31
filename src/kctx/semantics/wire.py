"""Positional-array JSON wire codec mirroring ``formal/Kctx/Codec.lean``.

Field order is the contract. Both sides carry ``SEMANTIC_VERSION``; the
conformance harness rejects mismatches. Errors are ``WireError`` with a
message prefixed exactly like the Lean decoder's (``expected ...`` /
``... not well-formed``)."""

from __future__ import annotations

import json
from typing import Any, Optional, Tuple

from kctx.semantics import model as M
from kctx.semantics.model import (
    Atom,
    Binding,
    Claim,
    ClaimProp,
    ClaimRef,
    Correction,
    CorrectionKind,
    CoverageWitness,
    Dep,
    DepKind,
    Derivation,
    EvalCtx,
    KB,
    ObsOutcome,
    RuleId,
    Scope,
    SupportRole,
    Ttl,
)
from kctx.semantics.wellformed import (
    record_wf_claim,
    record_wf_correction,
    record_wf_derivation,
    record_wf_observation,
)


class WireError(ValueError):
    pass


def _field(a: list, i: int) -> Any:
    if i >= len(a):
        raise WireError("missing field")
    return a[i]


def _dec_str(x: Any) -> str:
    if not isinstance(x, str):
        raise WireError("expected string")
    return x


def _dec_bool(x: Any) -> bool:
    if not isinstance(x, bool):
        raise WireError("expected bool")
    return x


def _dec_int(x: Any) -> int:
    # JSON numbers: accept ints only (no silent float coercion).
    if isinstance(x, bool) or not isinstance(x, int):
        raise WireError("expected int")
    return x


def _dec_list(x: Any) -> list:
    if not isinstance(x, list):
        raise WireError("expected array")
    return x


# ---- components (pure parsers; unconditional round-trips) ----


def enc_scope(s: Scope) -> list:
    return [s.project, s.extra]


def dec_scope(j: Any) -> Scope:
    a = _dec_list(j)
    if len(a) != 2:
        raise WireError("expected scope [project, extra]")
    project, extra = _dec_str(_field(a, 0)), _dec_str(_field(a, 1))
    if not project:
        raise WireError("scope.project empty")
    return Scope(project, extra)


def enc_claim_ref(r: ClaimRef) -> list:
    return [r.id, r.rev]


def dec_claim_ref(j: Any) -> ClaimRef:
    a = _dec_list(j)
    if len(a) != 2:
        raise WireError("expected claimRef [id, rev]")
    i, r = _dec_str(_field(a, 0)), _dec_str(_field(a, 1))
    if not i or not r:
        raise WireError("empty claim ref")
    return ClaimRef(i, r)


def enc_atom(a: Atom) -> list:
    return [a.subject, a.predicate, list(a.args)]


def dec_atom(j: Any) -> Atom:
    a = _dec_list(j)
    if len(a) != 3:
        raise WireError("expected atom [subject, predicate, [args]]")
    subject = _dec_str(_field(a, 0))
    predicate = _dec_str(_field(a, 1))
    args = tuple(_dec_str(x) for x in _dec_list(_field(a, 2)))
    return Atom(subject, predicate, args)


def enc_prop(p: ClaimProp) -> list:
    if p.tag == "atom":
        return ["atom", enc_atom(p.atom)]
    if p.tag == "conj":
        return ["conj", [enc_atom(x) for x in p.atoms]]
    return ["allChecked", p.predicate, list(p.members)]


def dec_prop(j: Any) -> ClaimProp:
    a = _dec_list(j)
    if not a:
        raise WireError("bad claimProp")
    tag = _dec_str(_field(a, 0))
    if tag == "atom" and len(a) == 2:
        return ClaimProp.of_atom(dec_atom(_field(a, 1)))
    if tag == "conj" and len(a) == 2:
        return ClaimProp.conj(tuple(dec_atom(x) for x in _dec_list(_field(a, 1))))
    if tag == "allChecked" and len(a) == 3:
        predicate = _dec_str(_field(a, 1))
        members = tuple(_dec_str(x) for x in _dec_list(_field(a, 2)))
        return ClaimProp.all_checked(predicate, members)
    raise WireError("bad claimProp")


def enc_ttl(t: Ttl) -> Any:
    if t.tag == "expireAfter":
        return ["expireAfter", t.secs]
    return t.tag


def dec_ttl(j: Any) -> Ttl:
    if isinstance(j, str) and j in ("noExpiry", "missing"):
        return Ttl(j)
    a = _dec_list(j)
    if len(a) == 2 and _dec_str(_field(a, 0)) == "expireAfter":
        return Ttl("expireAfter", _dec_int(_field(a, 1)))
    raise WireError("bad ttl")


_OBS_OUTCOMES = {e.value: e for e in ObsOutcome}
_ROLES = {e.value: e for e in SupportRole}
_RULES = {e.value: e for e in RuleId}
_DEPKINDS = {e.value: e for e in DepKind}
_CKRINDS = {e.value: e for e in CorrectionKind}


def enc_dep(d: Dep) -> list:
    return [d.kind.value, d.target, d.digest]


def dec_dep(j: Any) -> Dep:
    a = _dec_list(j)
    if len(a) != 3:
        raise WireError("expected dep [kind, target, digest]")
    k = _dec_str(_field(a, 0))
    if k not in _DEPKINDS:
        raise WireError("bad dep kind")
    return Dep(_DEPKINDS[k], _dec_str(_field(a, 1)), _dec_str(_field(a, 2)))


def enc_witness(w: CoverageWitness) -> list:
    return [enc_scope(w.scope), list(w.members), w.complete]


def dec_witness(j: Any) -> CoverageWitness:
    a = _dec_list(j)
    if len(a) != 3:
        raise WireError("expected witness [scope, [members], complete]")
    scope = dec_scope(_field(a, 0))
    members = tuple(_dec_str(x) for x in _dec_list(_field(a, 1)))
    complete = _dec_bool(_field(a, 2))
    if not scope.project:
        raise WireError("witness scope empty")
    return CoverageWitness(scope, members, complete)


def enc_eval_ctx(c: EvalCtx) -> list:
    return [
        c.now,
        c.require_fresh_evidence,
        c.require_validated,
        c.require_uncontested,
    ]


def dec_eval_ctx(j: Any) -> EvalCtx:
    a = _dec_list(j)
    if len(a) != 4:
        raise WireError("expected ctx [now, rf, rv, ru]")
    return EvalCtx(
        now=_dec_int(_field(a, 0)),
        require_fresh_evidence=_dec_bool(_field(a, 1)),
        require_validated=_dec_bool(_field(a, 2)),
        require_uncontested=_dec_bool(_field(a, 3)),
    )


# ---- records (parse + recordWf admission = T01) ----


def enc_observation(o: M.Observation) -> list:
    return [
        o.id,
        o.outcome.value,
        o.observed_at,
        enc_ttl(o.ttl),
        o.system,
        o.locator,
    ]


def dec_observation(j: Any) -> M.Observation:
    a = _dec_list(j)
    if len(a) != 6:
        raise WireError("expected observation [id, outcome, observedAt, ttl, system, locator]")
    oc = _dec_str(_field(a, 1))
    if oc not in _OBS_OUTCOMES:
        raise WireError("bad obs outcome")
    o = M.Observation(
        id=_dec_str(_field(a, 0)),
        outcome=_OBS_OUTCOMES[oc],
        observed_at=_dec_int(_field(a, 2)),
        ttl=dec_ttl(_field(a, 3)),
        system=_dec_str(_field(a, 4)),
        locator=_dec_str(_field(a, 5)),
    )
    if not record_wf_observation(o):
        raise WireError("observation not well-formed")
    return o


def enc_claim(c: Claim) -> list:
    return [enc_claim_ref(ClaimRef(c.id, c.rev)), enc_prop(c.prop), enc_scope(c.scope)]


def dec_claim(j: Any) -> Claim:
    a = _dec_list(j)
    if len(a) != 3:
        raise WireError("expected claim [ref, prop, scope]")
    ref = dec_claim_ref(_field(a, 0))
    prop = dec_prop(_field(a, 1))
    scope = dec_scope(_field(a, 2))
    c = Claim(id=ref.id, rev=ref.rev, prop=prop, scope=scope)
    if not record_wf_claim(c):
        raise WireError("claim not well-formed")
    return c


def enc_binding(b: Binding) -> list:
    return [b.obs, enc_claim_ref(b.ref), b.role.value]


def dec_binding(j: Any) -> Binding:
    a = _dec_list(j)
    if len(a) != 3:
        raise WireError("expected binding [obs, ref, role]")
    role = _dec_str(_field(a, 2))
    if role not in _ROLES:
        raise WireError("bad support role")
    b = Binding(
        obs=_dec_str(_field(a, 0)),
        ref=dec_claim_ref(_field(a, 1)),
        role=_ROLES[role],
    )
    if not b.obs or not b.ref.id or not b.ref.rev:
        raise WireError("binding not well-formed")
    return b


def enc_correction(c: Correction) -> list:
    return [c.kind.value, enc_claim_ref(c.target), c.recorded_at]


def dec_correction(j: Any) -> Correction:
    a = _dec_list(j)
    if len(a) != 3:
        raise WireError("expected correction [kind, target, recordedAt]")
    k = _dec_str(_field(a, 0))
    if k not in _CKRINDS:
        raise WireError("bad correction kind")
    c = Correction(
        kind=_CKRINDS[k],
        target=dec_claim_ref(_field(a, 1)),
        recorded_at=_dec_int(_field(a, 2)),
    )
    if not record_wf_correction(c):
        raise WireError("correction not well-formed")
    return c


def _enc_opt(f, o: Optional[Any]) -> list:
    return ["none"] if o is None else ["some", f(o)]


def _dec_opt(g, j: Any) -> Optional[Any]:
    a = _dec_list(j)
    if a == ["none"]:
        return None
    if len(a) == 2 and _dec_str(_field(a, 0)) == "some":
        return g(_field(a, 1))
    raise WireError("expected option")


def enc_derivation(d: Derivation) -> list:
    return [
        d.id,
        d.rule.value,
        [[enc_claim_ref(r) for r in g] for g in d.premise_groups],
        enc_claim_ref(d.conclusion),
        enc_prop(d.conclusion_prop),
        enc_scope(d.scope),
        [enc_dep(x) for x in d.footprint],
        _enc_opt(lambda i: i, d.evidence),
        _enc_opt(enc_witness, d.witness),
    ]


def dec_derivation(j: Any) -> Derivation:
    a = _dec_list(j)
    if len(a) != 9:
        raise WireError(
            "expected derivation [id, rule, groups, conclusion, prop, scope, footprint, evidence, witness]"
        )
    rule = _dec_str(_field(a, 1))
    if rule not in _RULES:
        raise WireError("bad rule")
    d = Derivation(
        id=_dec_str(_field(a, 0)),
        rule=_RULES[rule],
        premise_groups=tuple(
            tuple(dec_claim_ref(r) for r in _dec_list(g))
            for g in _dec_list(_field(a, 2))
        ),
        conclusion=dec_claim_ref(_field(a, 3)),
        conclusion_prop=dec_prop(_field(a, 4)),
        scope=dec_scope(_field(a, 5)),
        footprint=tuple(dec_dep(x) for x in _dec_list(_field(a, 6))),
        evidence=_dec_opt(_dec_str, _field(a, 7)),
        witness=_dec_opt(dec_witness, _field(a, 8)),
    )
    if not record_wf_derivation(d):
        raise WireError("derivation not well-formed")
    return d


def enc_kb(kb: KB) -> list:
    return [
        kb.head,
        [enc_observation(o) for o in kb.observations],
        [enc_claim(c) for c in kb.claims],
        [enc_binding(b) for b in kb.bindings],
        [enc_derivation(d) for d in kb.derivations],
        [enc_correction(c) for c in kb.corrections],
        [[enc_claim_ref(r), dg] for r, dg in kb.validations],
    ]


def dec_kb(j: Any) -> KB:
    a = _dec_list(j)
    if len(a) != 7:
        raise WireError(
            "expected kb [head, obs, claims, bindings, derivations, corrections, validations]"
        )
    validations = []
    for p in _dec_list(_field(a, 6)):
        pa = _dec_list(p)
        if len(pa) != 2:
            raise WireError("expected validation [ref, digest]")
        validations.append((dec_claim_ref(_field(pa, 0)), _dec_str(_field(pa, 1))))
    return KB(
        head=_dec_str(_field(a, 0)),
        observations=tuple(dec_observation(x) for x in _dec_list(_field(a, 1))),
        claims=tuple(dec_claim(x) for x in _dec_list(_field(a, 2))),
        bindings=tuple(dec_binding(x) for x in _dec_list(_field(a, 3))),
        derivations=tuple(dec_derivation(x) for x in _dec_list(_field(a, 4))),
        corrections=tuple(dec_correction(x) for x in _dec_list(_field(a, 5))),
        validations=tuple(validations),
    )
