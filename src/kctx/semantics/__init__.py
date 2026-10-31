"""Version 2 pure semantic core, mirrored by ``formal/Kctx``.

Public typed operations live in ``checker`` and ``workflow``; ``wire`` validates
strict schema/semantic versions, Unicode scalar strings, closed object records
and global KB invariants. Unpaired UTF-16 surrogates reject before semantic decoding.
Source, revision, content, project, actor, checker and authored revision identities
are nominal domain values. Missing optional identities are ``None``, never empty
valid IDs; codecs alone preserve legacy empty-string unknown spellings.
All time, snapshot, policy, checker, ruleset and intended-use inputs are explicit.
The core never reads a clock, source, repository, process or database.
Policy TTL is a three-way sum: expiry duration, explicit no-expiry, or missing
policy. Wire values are respectively a natural integer, ``{"tag":"noExpiry"}``,
or ``null``; no-expiry never excuses a future observation.
The concrete JSON protocol bounds formula/witness depth to 256 constructors,
including the root. This explicit transport bound does not restrict the internal
finite-witness language or turn overflow into accepted evidence.

Support is recursive finite evidence, independent of freshness and contestation.
Negative attestation is independent atomic evidence, not negation by absence.
Finite coverage requires an exact inventory-completeness attestation as well as
retained inventory bytes and recursive evidence for every required member.
Captured leaves must match explicit context source/revision/content selections;
retention of an older observation never makes it current automatically.
Receipts compare computed typed transitive inputs, not caller-supplied digests.

``plan_valid`` checks an unsigned candidate without publishing. ``apply_plan``
requires an exact ``VerifiedApproval`` supplied separately by an authenticated
adapter; candidate JSON cannot grant itself this capability. The reference
harness models trusted external approvals separately from ordinary requests.
Signed ordinary and selection plans bind the complete base evaluation context,
not just a reusable policy identifier or target claim.
Rejected and replayed operations leave both KB and applied journal unchanged.
``apply_selection`` publishes a forward snapshot with a selected retained claim
set; it never replaces the current ledger or drops later corrections. Selection
approvals and retained snapshots are separate authenticated adapter inputs.

The Nagini usable-policy twin verifies only the Boolean conjunction leaf, not
recursive checking, receipt authentication or storage publication. Full-response
Lean/Python conformance and independent golden/mutation cases cover the Python
composition; storage and signature adapter qualification are separate obligations.
"""
