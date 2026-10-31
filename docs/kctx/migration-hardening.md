# Migration hardening after the first real v2 migration

## Context

A first real migration from the v1 tools (`kb@e562c7b:tools/kctx` plus the
external cite tool) reported eight defects and one design question against the
v2 baseline, each with a synthetic repro. Every item was re-derived on this
repository before admission. Two of the reporter's candidates were already
deliberate v2 decisions and are rejected here with the controlling evidence;
one design question is answered by documentation, not code.

## Decision

Fix the eight verified defects. A record that one reader cannot decode must
limit that record, never the whole command; evidence fields address evidence,
never bare prose; declared options either take effect or are not declared;
and scan-time hardening must not make ordinary trees unscannable.

## Admitted and landed

| ID | Defect | What landed |
| --- | --- | --- |
| C9 | `proposal gate --rev <org/repo@sha>` recorded a result that reads as `unk` | `--rev` is retained verbatim in a new `repo_rev` field; the gate-definition digest in `rev` is always computed from the authored table, so repository evidence never overwrites the binding |
| C2 | Relationship `evidence` accepted only a bare slug; v1 locator data aborted `impact` for every asset | The field accepts the closed evidence-address grammar — `ev:<home>/<stem>` or a code locator `org/repo@<sha>:<path>[:line]` (v1's own format); bare slugs that address nothing are rejected with the accepted forms named; `uses ev:…` finds relationships citing the address |
| C3 | One malformed signature aborted `stale --project <unrelated>` and `match` | Aggregate readers (`impact`, `match`, `stale`) skip unreadable relationship/signature/investigation/correction records, disclose each in `warnings`, and exit partial (2); `validate` keeps reporting every bad record strictly |
| C1 | Legacy flat-file `applied` proposals failed `validate` with a seven-cause message naming none; no documented path to validity | `validate` names the exact failed predicates; `gate` now binds the published candidate (the first write also introduces the material `profile` field, which previously self-invalidated the binding); the workflows guide documents the adoption recipe; the strict rule itself stays (see Rejected) |
| C6 | One malformed citation token aborted the whole `cite` scan with no file or line | Scans use the opener-aware tokenizer shared with the graph extractor; a bad token is a located `unverifiable` result (`cite check`, exit 3) or a `malformed: …` entry (`cite stale`, exit 2); an unterminated token no longer swallows its successor |
| C7 | Any symlink under the scan root aborted `cite stale`/`cite check`/`stale` | Walks skip non-Markdown links unread (a git-ignored `.venv` link no longer kills the scan); Markdown-suffixed links, explicitly selected links, and links on the path are still refused |
| C12 | Read-only scans held one descriptor per Markdown file (~1000 files ⇒ EMFILE) | Read-only acquisition reads each leaf once and releases its descriptor; write-back runs keep the held-descriptor protocol they need |
| C8 | `knowledge explain --limit/--continuation` were declared and ignored | Both options are removed; `explain` takes a request and optional release only |
| C11 | One generic "candidate rejected by calculus preflight" for stale, future-dated and unsupported candidates | `checker.assessment_gaps` names each failed policy requirement; the rejection message carries them (e.g. `observations are stale under policy ttl`, `no accepted witness of the claim's polarity (support=none)`) |

## Acceptance gates

| id | claim | check | when | by |
|---|---|---|---|---|
| MH1 | Repository evidence never breaks gate binding | `tests/test_gates_rev.py::RepositoryEvidenceTest` records a gate with `repo_rev` and asserts `show` reports `pass` | land | maintainer |
| MH2 | v1 locator evidence decodes; `impact` traverses it | `tests/test_reader_tolerance.py` round-trips a locator relationship and traverses it without warnings | land | maintainer |
| MH3 | One unreadable record never aborts a cross-cutting reader | `tests/test_reader_tolerance.py` breaks a relationship/signature file and asserts `impact`/`match`/`stale` complete with disclosed warnings | land | maintainer |
| MH4 | Legacy decided records report named predicates and can be adopted | `tests/test_validate.py::LegacyProposalValidationTest` asserts the message names the missing bindings and that the adoption recipe reaches `ok: true` | land | maintainer |
| MH5 | Malformed tokens are located, scans continue | `tests/test_citation_scan.py::MalformedTokenScanTest` asserts per-token results with file/line and exit 3 | land | maintainer |
| MH6 | Non-Markdown links are skipped; Markdown links still refused | `tests/test_contained_citations.py` walk-link test plus the pre-existing refusal tests | land | maintainer |
| MH7 | Read-only scans release descriptors; write-backs retain them | `tests/test_contained_citations.py::ReadOnlyDescriptorTest` compares open-fd counts inside both scan kinds | land | maintainer |
| MH8 | `explain` declares no unused option | `tests/test_cli_commands.py::test_knowledge_explain_declares_no_unused_options` | land | maintainer |
| MH9 | Preflight rejections name their assessment gaps | `tests/semantics/test_core.py::AssessmentGapTests` and the end-to-end propose repro distinguish stale, unsupported and inapplicable | land | maintainer |
| MH10 | Python↔Lean authored-workflow twin stays identical | `formal/Kctx/Workflow.lean` `authoredCandidateValid` is byte-identical to the baseline; `semantics.test_core` golden decisions pass | land | maintainer |

## Rejected, with evidence

- **C1's main ask — waive decided-status bindings for `legacy_limited`
  records.** The reviewed semantic corpus pins the opposite:
  `scripts/semantic_cases.py` case `authored-legacy-still-needs-gate` (and its
  `-candidate` twin) asserts a legacy proposal targeting `applied` without
  bound gates is invalid, and Q26 forbids modern records acquiring a legacy
  exemption. A historical record that never earned its status stays invalid
  until adopted or superseded; what was actually missing — a message that
  names the predicates, a binding that survives its own first write, and a
  documented recipe — is landed.
- **C5 (reporter already dropped) and the C1 modern sub-case** — deliberate v2
  changes recorded in `PORTING.md` and `tests/test_validate.py`
  (`test_unbound_historical_gate_does_not_authorize_applied_status`).

## Design answer, not a defect

- **C10 — per-release TTL.** The TTL is a policy parameter of the signed
  evaluation context. Each release re-assesses all of its claims under its own
  approved policy, so a signed TTL change can make an unchanged, never
  re-observed claim fresh — that is the operator authorizing a policy event,
  consistent with D37, and now stated in [calculus.md](calculus.md). Whether a
  TTL change should also appear in the admission plan's item delta is an open
  product question; no behavior changed here.

## Blast-radius rule going forward

A reader that aggregates a collection (`impact`, `match`, `stale`) skips an
undecodable record and discloses it as a warning with exit 2 (partial). A
reader that names a record (`sig show`, `asset show`, `proposal show`) or the
whole-collection validator (`validate`) stays strict. Missing evidence is
never converted into an apparently complete successful answer.
