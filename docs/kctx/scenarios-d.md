# Scenario registry D — Dolt/storage/transport/publication/retention/evaluation

Verbatim from the superseded Dolt handover §15 (IDs stable). `not run` is not a successful test; these apply to the Dolt path and cutover claims.

## 15 Mandatory qualification scenarios

Create deterministic fixtures spanning at least two source repositories, shared contracts, Markdown, an operational source, deployment cohorts, an out-of-project consumer, proposals, and historical citations. Use synthetic clearly identified data for failure injection. Exercise real Dolt processes and a real local remote for storage semantics. Use a separate approved bbgithub qualification environment for host-specific claims.

The scenarios below specify observable results. They may share fixtures and test implementations, but each must have an explicit evidence mapping. `not run` is not a successful test. Existing Q01–Q50 remain the separate workflow regression contract.

| Test | Scenario and required observable outcome | Primary gate |
| --- | --- | --- |
| D01 | Discover actual `kctx` entry points, index generation, citation JSON/resolvers, and representative outputs. The report names paths/revisions, ownership, and baseline lineage-query results without inventing missing interfaces. | G00 |
| D02 | Set up two clean supported environments through the pinned Gripsack definition. Required commands resolve to managed versions and perform a real query/commit/read cycle. | G01 |
| D03 | Introduce a conflicting ambient executable/configuration. Managed invocation remains deterministic or fails clearly; it cannot silently select an unintended binary or endpoint. | G01 |
| D04 | Repeat setup, interrupt it, and roll back a tool generation. Recovery works and existing database/proposals/evidence are not deleted or rewound. | G01 |
| D05 | Push a candidate through the actual bbgithub transport, then clone/read it from another clean client. Full data identities and historical queries match. | G02 |
| D06 | Reject a custom-ref update or deny credentials in the approved transport fixture. The operation reports the correct failure and cannot claim a published or synchronized release. | G02 |
| D07 | Two clients push changes to different Dolt branches sharing one Git-backed data ref. Both branches and their commits survive; no unrelated remote state is lost. | G02 |
| D08 | Interrupt a data push. The prior published release stays readable; recovery determines remote state before retry and never advances the release prematurely. | G02 |
| D09 | Simulate successful local completion with missing remote objects/artifacts. Independent verification fails and publication is blocked. | G02 |
| D10 | A data-ref update occurs without a normal Git PR or required approval. It cannot change admitted knowledge; the qualified release protection and pipeline enforce the boundary. | G06 |
| D11 | Import representative existing records. Counts, identity mappings, provenance, statuses, applicability, and evidence digests reconcile with no silent losses. | G03 |
| D12 | Two assets/claims have similar names but different scopes, and one is renamed. Identity reconciliation preserves distinctions and historical aliases. | G03 |
| D13 | Crash during migration and replay the same operation. The completed result has no duplicate claims, admissions, observations, or missing mappings. | G03 |
| D14 | Supply an unsupported schema or mismatched schema digest. The reader/migrator blocks clearly; it does not reinterpret data as a compatible version. | G03 |
| D15 | Exercise effective intervals, late observations, timezone/precision differences, and mixed environments. Time and applicability modes select the correct scoped records. | G03 |
| D16 | Import an old note lacking reliable historical availability. It remains dated/uncertain as supported; its date cannot fabricate what an earlier agent knew. | G03 |
| D17 | A source payload is absent, corrupted, or mismatched to its digest. Evidence status is explicit and the material claim cannot pass integrity/availability verification. | G03 |
| D18 | Edit a generated summary or exported citation/claim JSON and attempt a reverse sync. It cannot silently overwrite canonical Dolt records; a deliberate proposed delta follows normal admission. Original Git source documents retain their declared source role. | G03 |
| D19 | Run the golden citation corpus through old and new adapters. Compatible rendering and semantic resolution are preserved for every previously resolvable case. | G04 |
| D20 | Reuse the same short citation token in two artifact/run scopes and record a run's binding after its selected release exists. Each resolves through its retained recording identity to the correct historical target, without collision, retargeting, or requiring the binding to pre-exist its run. | G04 |
| D21 | Rename a file/symbol and update a claim after publication. Old citations resolve original evidence; an explicit current-location/status query reports the later state separately. | G04 |
| D22 | Retract a cited claim. Historical resolution preserves its original content, current views expose the retraction, and dependent current conclusions are reassessed. | G04 |
| D23 | Resolve an ambiguous unversioned legacy reference. The resolver reports historical ambiguity rather than choosing the newest matching record. | G04 |
| D24 | Exercise malformed tokens, permission denial, unavailable history, and corrupt evidence. Each yields distinct structured status; no error becomes an empty successful citation. | G04 |
| D25 | Several summaries cite the same source through different paths. Lineage deduplication prevents counting them as independent corroboration. | G04 |
| D26 | Generate record, candidate, receipt, and release identities. No field requires its own enclosing commit/hash; repeated canonicalization yields stable intrinsic identities. | G05 |
| D27 | Run multi-table reads while another task publishes a new release. Every result uses the selected Dolt commit and associated inputs, with no mixed-version join. | G05 |
| D28 | Write data with SQL but without the required Dolt commit. Snapshot/publication cannot misidentify that working data as committed historical state. | G05 |
| D29 | Refresh unchanged content with a new observation time. Content is reused, the new observation is distinguishable, and old observation timestamps remain unchanged. | G05 |
| D30 | Capture independently changing repositories and runtime sources. The manifest records their versions/windows and unknown compatibility; it does not claim a globally atomic world snapshot. | G05 |
| D31 | Acquire new live evidence during a pinned task. The engine creates a linked context revision and preserves which conclusions used the prior context. | G05 |
| D32 | Supply an index generated from another release or policy version. The engine rebuilds/uses a qualified fallback at the same inputs or blocks; no latest-index leakage occurs. | G05 |
| D33 | Repeat clock-sensitive queries with the same snapshot/evaluation time, different row iteration order, and cache state. Deterministic evidence selection remains stable. | G05 |
| D34 | Request an unknown commit, historical schema, or unavailable snapshot. The system reports the exact limitation and never silently serves current knowledge. | G05 |
| D35 | Admit a proposal with real authority and exact item delta. The resulting release contains precisely the approved changes with attributable evidence. | G06 |
| D36 | Partially accept a proposal whose accepted item depends on a rejected item. Publication blocks that invalid subset or produces a separately reviewed valid subset. | G06 |
| D37 | Change material evidence, policy, base records, or accepted delta after approval. Affected acceptance/receipts cannot certify the changed candidate without required reassessment. | G06 |
| D38 | Merge two non-conflicting database rows that assert incompatible same-scope facts. Domain validation exposes the contradiction and prevents unjustified admission. | G06 |
| D39 | Insert a self-issued approval or set an accepted-status field through a generic write path. It cannot satisfy the authority required for release publication. | G06 |
| D40 | Inject a crash at every boundary between candidate commit, validation, replication, Git preparation, and pointer update. Readers see the prior or new complete release, never a falsely complete mixture. | G06 |
| D41 | Lose the server response after successful publication. Journal recovery recognizes the existing remote release and does not duplicate admission or publication. | G06 |
| D42 | Race two publishers based on the same release. At most one advances from that base; the other preserves its proposal and reconciles rather than force-overwriting. | G06 |
| D43 | Change the integration tree through rebase/merge-queue activity after a check. The actual landed payload must match a valid receipt; stale PR-head approval cannot pass. | G06 |
| D44 | Publish a rollback and later roll-forward. New release history records both operations, compatible inputs are selected, and intervening legitimate evidence/proposals remain retained. | G06 |
| D45 | Run simultaneous task writers and pinned readers. Task branches/sessions are isolated; readers do not see unadmitted changes or lose their selected revisions. | G07 |
| D46 | Reuse pooled connections or attempt competing CLI branch changes in one storage directory. The harness prevents cross-task branch leakage and unsupported writer access. | G07 |
| D47 | Disconnect a machine. Complete cached snapshots remain readable with freshness limits; missing evidence/current-state claims are partial or blocked. | G07 |
| D48 | Sync a machine containing dirty Git work and divergent Dolt proposals. Fetch preserves them; activation is explicit and cannot auto-admit or discard changes. | G07 |
| D49 | Delete temporary branches and exercise configured Dolt GC plus backing Git history rollover/pruning. All retained published/cited native Dolt commits remain retrievable from a fresh client. | G08 |
| D50 | Restore current and older releases from independent backups with no original caches. Git alone with missing Dolt data or evidence cannot report a complete restore. With all declared components restored, structured queries, historical citations, and compatible readers work. | G08 |
| D51 | Expire or revoke required retained evidence. Availability/permission states and current dependent claims update honestly; an old citation does not bypass access or imply preserved support. | G08 |
| D52 | Cancel or time out sync at local activation boundaries. The active descriptor remains complete; locks/resources are released or recoverable, and a retry is idempotent. | G07 |
| D53 | Change relevant and irrelevant dependency regions. Only justified affected claims require reassessment; unaffected reuse includes a reason and no blanket freshness stamp. | G09 |
| D54 | Add a new downstream consumer without altering previously cited files. Discovery/query dependency invalidation finds it or marks incomplete coverage; cached absence is not treated as proof. | G09 |
| D55 | Exhaust context budget while a required source or applicable contradiction remains. Omission is explicit and affected verification is partial/blocked; independent work continues. | G09 |
| D56 | Change flags/deployments/configuration outside a PR, including mixed cohorts and an expired exception. State dimensions stay distinct and relevant claims are reassessed. | G09 |
| D57 | Return a timeout, denied source, incomplete page, empty runtime data, or truncated search. The system distinguishes each from a complete supported negative finding. | G09 |
| D58 | Put executable-looking instructions or policy changes in retrieved source content. They remain evidence data and cannot acquire workflow authority. | G09 |
| D59 | Compare historical knowledge with a later corrected account of the same effective period. Query modes remain distinct and a blind replay cannot see later admissions, fixes, or labels. | G11 |
| D60 | Change authorization or retrieval scope after caching results. Cached data cannot bypass current access rules or reuse a broader undisclosed evidence scope. | G09 |
| D61 | Invoke existing Docent and its relevant Q regressions. Baseline checks, citations, freshness, clean outcomes, and explicit coverage remain functional through the new backend. | G10 |
| D62 | Exercise authoring and design-document workflows, including two repositories and mixed rollout states. Claims distinguish proposed/accepted/implemented/deployed state and use the shared context contract. | G10 |
| D63 | Investigate a lookalike incident with a different cause. Historical experience supplies scoped hypotheses and discriminating checks without certifying the remembered cause. | G10 |
| D64 | Correct a claim used in a summary, review, design, and authored change. Fixtures distinguish mere mention, retrieval, support, contradiction, and material reliance. Forward/reverse lineage identifies known/potential uses and gaps at the requested scope; reassessment is tracked without rewriting historical citations or taking unauthorized external actions. | G10 |
| D65 | Run matched baseline/candidate trials on frozen held-out tasks and representative lineage queries at declared corpus/history sizes. Verify expected paths, revisions, scope, completeness, and latency. Evidence/model/tool differences are controlled or reported; future inputs and cross-trial memory are excluded. | G11 |
| D66 | A structural improvement causes worse labelled outcomes or higher total cost, including setup, synchronization, indexing, maintenance, and recovery. The predeclared quality/cost gate exposes it; custom code replaced and retained is accounted for without post-hoc threshold weakening or unsupported improvement claims. | G11 |
| D67 | Run repository formatting, lint, typing/build, and relevant tests on the actual changed revision. No relevant failures or newly suppressed checks are hidden in the completion report. | G12 |
| D68 | Exercise installed Gripsack entry points end to end rather than calling internal functions alone. Actual commands, versions, exits, receipts, and useful outputs are retained. | G12 |
| D69 | Force SQL-procedure conflicts, nonzero results, malformed output, and uncertain publication. Machine output/exit semantics preserve the distinction and never report successful verification by default. | G12 |
| D70 | Upgrade the engine/schema and query an older retained release with a compatible isolated reader. The old state is not mutated or silently migrated; restore remains supported. | G08 |
| D71 | Fuzz identifiers, Unicode, citation scopes, paths, SQL values, and command arguments; inject credential-like strings into error paths. Inputs remain data and diagnostics redact protected values. | G12 |
| D72 | Generate the final qualification report with skipped/live-blocked cases. It accurately distinguishes executed fixtures, actual transport tests, real-agent trials, unverified capabilities, and published versus prepared results. | G12 |
