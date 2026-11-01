# Review-tool feature requests: tracked fixes and local diff impact

## Decision before implementation

Accept FR1 and FR2 as authored-reference and retrieval features, not defects in
v2 and not new inference rules. The report names
`tnawara/kctx@1761409f88decb9ecfb6d1b2943461f9d45f6599`; C1–C12 remain separately
recorded in [migration-hardening.md](migration-hardening.md).

### Kernel and Lean assessment

No calculus, semantic version, wire schema, Lean model or theorem change is
required. `Signature.fix` and `fixed_at` are authored incident metadata, not
`Observation`, `Attestation`, `Witness` or `Receipt` fields. Diff hunks, citation
occurrences and inventory relationships select review candidates; they do not
establish positive/negative support, validate a claim or admit a source change.

The controlling contracts are [calculus.md](calculus.md), especially exact
scope, independent assessment dimensions and authenticated releases, and
[calculus-revision.md](calculus-revision.md), requirement 8 (bounded retrieval,
not inference by SQL). Lean's `retrieve`/`retrieveSelected` and Python's existing
`KnowledgeEngine.context` remain the assessment/retrieval boundary. The new
query must use that boundary rather than implement a second checker.

If a later proposal makes a merged PR prove an incident fixed, makes a textual
citation a proof premise, infers a contradiction from a changed line, or treats
inventory absence as a universal assertion, that is a separate semantic change
requiring calculus review and Lean obligations **before** implementation.

## FR1: tracked fix references

Extend the closed authored fix type from proposal identities to the union of
existing proposal identities and `EvidenceAddress`:

- a valid existing proposal ID (unchanged);
- `ev:<home>/<stem>` for an evidence record, which can retain a fixing PR or
  ticket and its citation;
- `org/repo@<sha>:<path>[:line[-line]]` for an exact code location.

Reuse `parse_evidence_address`; do not invent a second PR/ticket address grammar
or silently accept free text. Historical `org/repo#7` and `TICKET 1234` values
must be expressed as an evidence record or pinned code location. Preserving
valid proposal identities preserves a legitimate existing fix kind, not an
untyped legacy escape hatch. Writers, strict readers, reverse navigation and
graph extraction must agree on these references.

`fixed_at` stays explicit. An evidence address supplies identity/provenance,
not an inferred merge time or verification result. Regression detection keeps
its existing date rule: a citing investigation created after the signature's
`fixed_at` is an advisory regression candidate. No network request is needed to
record or reverse-query the fix. `uses <fix-address>` must find the signature;
the evidence record is the reverse-query handle for a PR/ticket-backed fix.

Rejected alternative: provider-specific PR/ticket types and automatic merge-time
lookup. They are viable future product choices but unnecessary to satisfy the
request; evidence addresses already support both and preserve the provider-
neutral kernel.

## FR2: local commit diff review checklist

Expose `kctx impact --diff <base>..<head> [--repo <local-path>]` and JSON-RPC
`authored.impact_diff`. Keep `impact <asset>` unchanged. `--repo` selects a local
Git repository; without it use the current directory, not the KB root. Resolve
both commits once from its object store. Never fetch, clone, consult a PR API,
run external diff/textconv helpers, or substitute working-tree bytes. This
supports committed but unpushed changes. The range is a two-endpoint comparison,
not triple-dot merge-base selection or a promise to include uncommitted edits.

The result identifies the resolved repository and exact base/head commits and
returns, per touched file:

1. Old/new paths, change kind and zero-context old/new hunk coordinates.
2. Same-file code citation occurrences from the authored Markdown scan, including
   citation location, original fields/range, and every demonstrable overlapping
   hunk with its coordinate side. Match repository identity, not a substring.
   An endpoint pin or identical historical blob permits coordinate comparison;
   other revisions remain visible as same-file/unmapped, not falsely nonoverlapping.
   Zero-length sides are insertion/deletion boundaries, not real changed lines.
   Renames retain both paths; binary and metadata-only changes remain visible
   without fabricated line ranges. Illustrative citations do not become assertions.
3. Inventory assets whose repository locator matches that repository (not a
   guessed file-ownership proof), their inbound and outbound relationships,
   bounded related/dependent assets with disclosed unexplored edges, and
   signatures explicitly listing the matched asset IDs.
4. Selected admitted claims relevant to those assets in one pinned completed
   release context, with the existing assessment and provenance intact. Relevance
   uses exact asset identities in structured formula subjects/arguments or scope
   selectors; it is a retrieval convention, never a semantic scope rule. The
   context's approved policy, intended use, source selections and scope are not
   weakened. Assessment time and pinned release are explicit. Missing or broken
   storage is not represented as an empty successful release.

Report `no_release` explicitly when no completed release exists. Authored data
still yields a useful checklist in that case. Missing configuration for an
existing release, unreadable records, malformed citations, unmappable ranges,
bounded traversal and bounded claim retrieval must have explicit statuses,
warnings or omission fields. All files in a query use the same selected release;
concurrent publication must not mix claim generations. The authored scan is a
workspace read and must not be described as a completed immutable KB generation.
An empty result only describes the stated scan/retrieval boundary; it does not
certify no dependencies, no contradictory claims or safe admission.

## Verification obligations

- Round-trip proposal and evidence/code fixes; reject untyped PR/ticket prose;
  reverse-query both evidence and code addresses; preserve regression date rules.
- Exercise actual CLI and JSON-RPC on a temporary local repository with unpushed
  commits, overlapping and nonoverlapping citations, a shifted/unknown pin,
  insertion/deletion, rename, and binary or metadata-only changes.
- Show inbound/outbound inventory links, directly attached signatures and
  explicit depth/coverage boundaries; disclose unreadable authored inputs.
- Exercise both no-release and genuinely authenticated Git/Dolt release paths.
  Only selected/context-applicable claims may appear; retain support/contrary
  evidence, freshness and provenance rather than promoting them to a safety verdict.
- Run affected contracts and package quality checks after integration. No claim
  that the new adapters are kernel-proved follows from the unchanged Lean model.

## Exercised integration

The real CLI and JSON-RPC smoke ran in the pinned
`kctx-verify:lean-4.21.0-dolt` image against temporary repositories and native
Dolt storage. It exercised six changed files (including rename, deletion,
insertion, binary and mode-only changes), unpushed commits with deliberately
different dirty worktree bytes, endpoint/identical-blob/unknown citation pins,
both relationship directions, attached signatures and reverse fix queries.
The same scenario returned `no_release` before publication, then the exact
authenticated release's assessed claim after signed admission. CLI and RPC
payloads agreed. The human rendering was exercised separately and uses expanded
records rather than clipping nested identifiers into narrow table cells.

The first added multi-claim retrieval fixture was correctly rejected because
its additional claims lacked accepted witnesses. The fixture now supplies
explicit attestations and derivations for every newly admitted claim; no
preflight condition was weakened. Graph tests use nominal node identities
rather than comparing nominal values to strings.

Strict package typing, nominal consumer contracts, source lint/formatting and
package/version contracts passed. The contract checker inspected the existing
proof report; this is not a claim of a new Lean build or proof of these adapters.

Final regression command: `python -m unittest discover -s tests` in that image:
**710 tests passed, no skips**. Retained regressions cover typed fixes,
graph/backlink queries, local diff boundaries and authenticated asset-context
retrieval. Diff CLI/RPC parity and human presentation were exercised by the
temporary smoke, which was removed after verification.
