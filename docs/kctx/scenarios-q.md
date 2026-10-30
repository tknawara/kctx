# Scenario registry Q — semantics, workflows, types, persistence, agent use

Verbatim from the superseded Lean handover §13.2 (IDs stable). Reproduce the relevant behavior in the complete checkout before changing expectations.

### 13.2 Mandatory scenario matrix

The following cases are requirements. Merge related cases into parameterized tests when that improves clarity; do not create one trivial test per table row solely to inflate counts.

| ID | Scenario and required outcome | Gates |
| --- | --- | --- |
| Q01 | Same spelling used as an AssetId and ProposalId cannot be interchanged in typed service calls. | G02 |
| Q02 | Malformed ID, unsafe relative path, invalid digest kind, and unsupported schema version are rejected at the boundary. | G02, G07 |
| Q03 | Aliases resolve uniquely; ambiguous aliases and short revisions produce explicit ambiguity, never latest-match selection. | G02, G11 |
| Q04 | Valid protocol values round-trip; unknown tags, duplicate keys/IDs, wrong scalar types, and missing fields are diagnosed. | G02, G05 |
| Q05 | Frozen domain values cannot change through a retained mutable input collection. | G02 |
| Q06 | All enabled operators and rules have theorem/function/fixture registry entries. | G04, G05 |
| Q07 | Missing theorem, hidden `sorryAx`, or unapproved axiom fails the proof job. | G04 |
| Q08 | A nontrivial valid model is constructible; every important precondition has positive examples. | G03, G04 |
| Q09 | Lean and Python agree on reviewed positive/negative derivations and generated transition sequences. | G05 |
| Q10 | Changed Python semantics without corresponding version/registry changes fails contract or conformance checks. | G05 |
| Q11 | Source bytes unchanged with matching complete footprint permits reuse under unchanged context. | G04, G05 |
| Q12 | Changed required dependency makes the affected derivation stale. | G05 |
| Q13 | An unrelated file change preserves a result whose footprint excludes it under a proved locality rule. | G05 |
| Q14 | New caller/file/member invalidates an “all members checked” result even if existing members are unchanged. | G05, G06 |
| Q15 | Missing, truncated, denied, or incomplete enumeration cannot establish absence or exhaustive coverage. | G05, G09 |
| Q16 | TTL equality, one tick after expiry, no-expiry policy, missing policy, and future-clock cases follow the declared convention. | G05 |
| Q17 | Copying/summarizing evidence does not reset observation time or drop dependencies. | G05 |
| Q18 | One broken supporting derivation leaves another valid independent derivation available. | G05 |
| Q19 | All support removed yields unsupported/unknown, not a proof of the opposite claim. | G05 |
| Q20 | Conflicting positive/negative support remains visible and the chosen policy handles contestation explicitly. | G05, G09 |
| Q21 | Navigation edges, reverse implications, and invalid scope restrictions cannot become accepted derivations. | G04, G05 |
| Q22 | A supersession edge alone does not validate its replacement; self/cyclic supersession is diagnosed. | G05, G06 |
| Q23 | Historical assessment remains reproducible after a later correction; current assessment changes appropriately. | G05, G14 |
| Q24 | Changed policy/rule/checker invalidates incompatible cached assessment even when source bytes are unchanged. | G05 |
| Q25 | Draft-to-proposed checks readiness; the previous bypass fixture is intentionally updated. | G06 |
| Q26 | Modern missing/malformed/duplicate gates cannot acquire a legacy exemption. | G06 |
| Q27 | A valid legacy exemption remains readable and explicitly limited; old paths/IDs are preserved. | G06, G07 |
| Q28 | Land/deploy/use passes on the wrong target or old gate definition do not authorize a transition. | G06 |
| Q29 | Applied transition checks landed references after combining same-command additions. | G06 |
| Q30 | Two landing attempts against one predecessor cannot both acquire the same exclusive transition. | G06, G08 |
| Q31 | Actor roles and acceptance history survive later landing/verification/regression. | G06 |
| Q32 | A violated required item can count as examined but cannot satisfy a policy requiring success. | G06, G09 |
| Q33 | Duplicate/copy-derived observations do not become independent corroboration. | G05, G06 |
| Q34 | Relevant staged, unstaged, binary, untracked, mode, and submodule changes affect worktree identity as specified. | G06, G08 |
| Q35 | Source movement during capture is detected; missing source produces unavailable, not unchanged. | G06, G08 |
| Q36 | Interrupted admission retains pending judgment work and does not confuse scan cursor with completed admission. | G06, G08 |
| Q37 | Dry run leaves canonical records, cursors, corrections, and published generation unchanged. | G06, G10 |
| Q38 | Malformed hypotheses cannot disappear from investigation conclusion checks. | G06 |
| Q39 | Promotion retries repair missing project pointers without duplication or origin deletion. | G06, G08 |
| Q40 | Correction failure between target/event/task writes is recoverable without lost pending reviews. | G06, G08 |
| Q41 | Updating known metadata preserves unknown frontmatter, custom sections, citations, code fences, and unrelated bytes. | G07 |
| Q42 | Duplicate headings/keys and invalid legacy list syntax produce diagnostics rather than silent loss. | G07 |
| Q43 | Existing comma/quote/Unicode citation fixtures remain intact, including multiple citations on one line. | G07 |
| Q44 | Missing/incompatible external citation provider returns unassessed/unavailable and cannot certify freshness. | G07, G09 |
| Q45 | Process interruption during immutable creation never exposes partial published JSON. | G08 |
| Q46 | Concurrent mutable writes detect predecessor conflicts; disk/permission errors are not retried indefinitely. | G08 |
| Q47 | Readers during a multi-record publication see a complete selected state, not a mixture. | G08, G11 |
| Q48 | Extractor/parser/schema/alias-map change forces a new generation despite unchanged KB SHA. | G11 |
| Q49 | Two different KB identities sharing a machine cannot overwrite each other's graph. | G11 |
| Q50 | Crash between graph data and metadata commits is detected and repaired; null mapping is not up to date. | G11, G12 |
| Q51 | Same-snapshot parity detects swapped destinations/revisions even when total binding counts match. | G11 |
| Q52 | Extraction diagnostics are retained with their original parser/config identity and replay consistently. | G11 |
| Q53 | `git archive` attributes, invalid UTF-8, missing blobs, and unsupported objects follow the declared extraction contract. | G11 |
| Q54 | Moving a citation by inserting prose changes its occurrence location without inventing a semantic evidence change. | G07, G11 |
| Q55 | Bounded impact on dense cyclic graphs terminates within resource limits and reports incomplete coverage. | G11, G15 |
| Q56 | Negative/oversized limits and depths are rejected; pagination stays on one immutable generation. | G09, G11 |
| Q57 | Graph reads remain pinned while another process refreshes or edits the working database. | G11, G12 |
| Q58 | Failed staged rebuild preserves the last usable generation; incorrect destination ownership is refused. | G08, G11 |
| Q59 | Actual Dolt schema constraints, migrations, CLI/CSV row types, and commit identity match adapter contracts. | G12 |
| Q60 | SQL transaction completion alone is not advertised as a retained Dolt snapshot. | G12 |
| Q61 | Independent clients push/fetch/clone against the selected remote and retrieve exact historical data. | G13 |
| Q62 | Remote concurrency/interruption and ambiguous completion preserve publication/operation identity. | G13 |
| Q63 | Clean restore with retained Git/Dolt/evidence reproduces selected historical results. | G14 |
| Q64 | Missing retained evidence or incompatible historical semantics returns an explicit replay limitation. | G14 |
| Q65 | Migration preserves IDs, exact citations, source links, and narrative content; second identical run is idempotent. | G10 |
| Q66 | Ambiguous or lossy migration records are quarantined for resolution rather than fabricated as valid. | G10 |
| Q67 | Old/new readers agree on compatibility fixtures and intentional policy changes have explicit expected differences. | G07, G10 |
| Q68 | Installed `kctx` resolves an explicit KB from an unrelated directory without using its code repository as the data root. | G09, G16 |
| Q69 | JSON output, exit codes, warning categories, and bounded explanations remain usable by existing agents. | G09 |
| Q70 | Runtime commands work without Lean, Lake, Elan, Docker, formal source, or reference binaries present. | G16 |
| Q71 | A fresh locked environment runs required checks without silently skipping selected capabilities. | G01 |
| Q72 | Deliberate semantic mutations are caught by proof/conformance/regression checks. | G04, G05 |
| Q73 | Held-out agent tasks preserve answer/review quality and show measured context/recheck cost. | G15 |
| Q74 | A lesson from one project does not become a universal rule or leak across incompatible scopes. | G09, G15 |
| Q75 | Cache eviction and cold startup affect performance but not semantic answers or completeness labels. | G15 |
| Q76 | Rollback selects a retained compatible release and preserves subsequent audit/correction history. | G10, G14, G17 |
