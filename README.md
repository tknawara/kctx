# kctx

A typed knowledge engine for retaining evidence, admitting scoped claims and
retrieving them across sessions. Git keeps authored assets and release manifests;
Dolt keeps versioned structured records and relationship projections. The pure
semantic core is specified in Lean and implemented in Python.

**Acquisition is not truth. A citation is not approval. A database join is not an
inference.** The engine keeps support, contrary evidence, freshness, validation,
authority and publication separate.

## Start with Docker Compose

No host Python, Lean, Dolt or package installation is required for this workflow.
Create one `config.toml` using paths visible inside the container:

```toml
root = "/kb"
graph_dir = "/state/graph"
knowledge_dir = "/state/knowledge"
cache_dir = "/state/citations"
log_dir = "/state/logs"
```

Run the installed CLI against your mounted workspace:

```sh
docker compose --profile runtime run --build --rm \
  --volume /absolute/path/to/kb:/kb \
  --volume /absolute/path/to/state:/state \
  --env KCTX_CONFIG=/kb/config.toml \
  kctx --json asset list
```

`KCTX_CONFIG` only locates the file. There is no CLI/env/config precedence for
individual settings. Without an explicit root setting, the CLI discovers a KB
by its workspace marker, never by assuming any Git repository is a KB.
[Configuration details](docs/kctx/config.md).

For an already managed Python environment, the same entry point is
`uv run --locked kctx`; `python -m kctx` is also supported. There are no root
module shims. The installed runtime does not need Lean or formal source files.

## Choose the right operation

| Need | Command family | Meaning |
| --- | --- | --- |
| Record entities and explicit relations | `asset`, `rel`, `impact` | Inventory and bounded navigation; absence is not proof of no dependents |
| Review an unpushed commit diff | `impact --diff BASE..HEAD [--repo PATH]` | Citation/hunk overlap, related inventory, signatures and pinned admitted claims; a checklist, not a safety verdict |
| Orient a session | `home`, `context`, `match`, `timeline`, `uses` | Authored-workspace navigation with provenance and coverage boundaries |
| Make or inspect durable citations | `cite make/check/stale/render` | Built-in grammar, exact source identity, current advisories and safe rendering |
| Refresh after source changes | `admit --repo …`, `admit <PR>` | Source/citation refresh and durable pending judgment work—not approval of new facts |
| Record work and evidence | `run`, `observe`, `cover`, `check`, `resume`, `checkpoint` | Immutable observations, retained input identity, coverage and eligibility |
| Manage authored workflows | `proposal`, `inv`, `ktlo`, `sig`, `dossier` | Typed state transitions and lossless authored-document updates |
| Correct knowledge and repair projections | `retract`, `correction recover` | Durable correction event first, then replayable target/review projections |
| Admit canonical structured knowledge | `knowledge capture/propose/sign/admit` | Exact captures, explicit candidates, authenticated approval and conditional publication |
| Read admitted knowledge | `knowledge context/explain` | Pinned claims, contrary evidence, assessment, provenance and bounded continuation |
| Recover, migrate or retain history | `knowledge recover/migrate/rollback/backup/restore` | Explicit recoverable operations; migration does not auto-admit prose |
| Query the relationship projection | `graph sync/status/uses/impact/diff/check`, `serve` | Completed immutable generations, exact binding parity and reusable read-only sessions |
| Diagnose records or operations | `validate`, `logs` | Aggregated typed diagnostics and redacted structured operation logs |

Put `--json` before the command for machine output. Exit codes remain `0` success,
`2` partial, `3` blocked and `1` error. Expected failures carry a stable category;
missing or unavailable evidence is not converted into an empty successful answer.
Use each command's `--help` for the exact supported parameters.

### Human output and agent transport

The CLI uses native Click groups and Rich help, tables and diagnostics. Human
results use stdout; warnings/errors and requested verbose events use stderr.
Color is detected separately for each stream; `NO_COLOR` and
`--color auto|always|never` control human presentation. Untrusted terminal
controls are escaped and markup-looking source text stays literal. JSON output
bypasses styling, including command-line errors. Full logs remain redacted JSONL.

`kctx serve` exposes the same application to agents over JSON-RPC 2.0, one JSON
frame per line. Initialize before sending operations:

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocol_version":"1"}}
{"jsonrpc":"2.0","id":2,"method":"cite.make","params":{"citation":{"kind":"web","fields":{"url":"https://example.com","q":"reference"}}}}
{"jsonrpc":"2.0","id":3,"method":"shutdown"}
```

Initialization returns exact method schemas and request-size bounds. Citation,
authored navigation, graph and knowledge methods share this process. Graph reads
stay on their pinned generation until `graph.refresh`; knowledge reads and
continuations retain their release identity. Responses include operation exit
state, generation and completeness. Signing with an operator-held private key
and filesystem backup/migration remain explicit CLI operations, not RPC methods.
See [the operational flows](docs/kctx/flows.md) and
`src/kctx/engine/schemas.py` for the supported method contracts.

## Citations are part of kctx

There is no external `cite` executable or `cite.py` loader:

```sh
kctx --json cite make ticket id=DRQS-7 'q=Which deployment changed?'
kctx --json cite check notes/
kctx --json cite stale notes/ --offline
kctx cite render notes/decision.md --format md
```

The public `⟦cite …⟧` syntax remains. Historical `rev`, `blob`, `span`, `L`,
`seen` and cited `state` are preserved. Refresh writes separate current advisory
fields such as `checked_at`, `current_rev`, `current_L` and `current_state`.
Rendering does not silently repoint a historical link or renew an observation's
age. Illustrative citations remain distinguishable from evidence.

Source reads and write-backs reject unsafe traversal/symlink targets. Secret
redaction covers rendering and diagnostics; authored regex redaction is bounded
and fails closed. See [citation flow and limits](docs/kctx/flows.md#citation).

## Authored workflows versus signed admission

A proposal's lifecycle is not the same thing as publication of admitted
knowledge. Authored proposal transitions validate the complete candidate using
the shared semantic predicates, bind gate results to material proposal/target/
environment/scope/checker identities, and preserve actor history. Actual landed
references must resolve. See [the workflow guide](docs/kctx/workflows.md).

Canonical knowledge admission additionally needs a trusted policy and detached
Ed25519 approval. Configure `knowledge_policy_digest` to the exact SHA256 of the
bootstrap `.kctx/knowledge-policy.json`; the policy holds public keys and allowed
uses, never private keys. The operator retains the signing key separately.

```sh
kctx --json knowledge capture --kind document --source docs/design.md \
  --revision <exact-source-revision> --file /path/to/design.md --observed-at <epoch>
kctx --json knowledge propose --candidate /path/to/candidate.json \
  --target-use review --now <epoch>
kctx --json knowledge sign <plan-id> --private-key /private/operator.pem --key-id reviewer
kctx --json knowledge admit <plan-id> --approval /path/to/approval.json
kctx --json knowledge context --request /path/to/context-request.json
```

`capture` retains supplied acquisition bytes and declared source identity; it does
not infer arbitrary prose claims. A candidate explicitly names its structured
claims, evidence, witnesses and context. Signing binds the complete candidate,
base, policy and material inputs—not a mutable `accepted` flag. Prepared native
commits are not current until the authenticated release publication succeeds.
[Admission and retrieval flows](docs/kctx/flows.md).

## Storage and history

- **Authored files:** existing inventory, proposal, incident and document layouts
  stay readable. Targeted edits preserve unknown sections, citation text and line
  endings. Nominal IDs and enums are decoded at boundaries.
- **Knowledge releases:** a completed Git release pins native Dolt data and
  retained signed inputs. Reads do not fall back to HEAD or WORKING. Forward
  rollback selects earlier admitted claims without deleting subsequent audit or
  correction history.
- **Relationship projection:** extraction binds source, parser, schema, semantic,
  configuration and engine identities. Candidate generations are isolated;
  publication selects only complete retained data. Equal counts are not enough:
  parity compares exact bindings.
- **Observations:** complete published JSON appears atomically. Git capture
  retains the declared raw worktree/index/submodule profile; missing or moved
  input is explicit. Coverage that an item was examined is distinct from
  eligibility to proceed.
- **Recovery:** operation journals are recovery hints, not authority. They are
  revalidated against signed inputs and retained objects before replay or
  publication. No live `.dolt` directory is committed as ordinary authored files.

[Detailed flows](docs/kctx/flows.md) · [Schemas and calculus](docs/kctx/calculus.md)

## Verification

```sh
# Locked Python checks, static misuse fixtures, behavior, Lean audit,
# full-response cross-host conformance and actual CLI/Dolt smoke
docker compose --profile verify run --build --rm verify &&

# Executable twin verification and production equivalence grids
docker compose --profile nagini run --build --rm nagini &&

# Installed runtime without Lean/Docker/formal artifacts
docker compose --profile verify run --build --rm runtime
```

The chain stops on the first failed stage. The runtime includes Git, Dolt and
the GitHub CLI; no host tool installation is needed beyond Docker Compose.

Additional real-process qualification is provided by
`scripts/qualify_storage.py`, `scripts/qualify_remote.py` and
`scripts/evaluate_kctx.py`. The [gate report](docs/kctx/gates.md) records exact
commands, source/fixture identities, outcomes and scope. Local Git/Dolt transport
is not represented as enterprise-policy qualification; deployment-specific checks
are left to the work agent as requested.

The Lean proofs establish the declared finite semantic model under explicit
proposition-specific evidence and authenticated-environment assumptions. Python
correspondence, cryptographic/source adapters, durable publication, native SQL,
restore and agent usefulness have separate executable evidence. A theorem count
alone is not a complete-system correctness claim.

## Architecture and future Rust host

Runtime code lives under `src/kctx`: `domain`, `codecs`, `semantics`, `citations`,
`services`, `adapters`, `graph` and `cli`. Formal code is under `formal/Kctx` and
is excluded from the runtime artifact.

- [Implementation/refactor decisions](docs/kctx/refactor-plan.md)
- [Sound calculus revision](docs/kctx/calculus-revision.md)
- [Rust implementation handover and R00–R13 gates](docs/kctx/greenfield-design.md)
- [Migration hardening after the first v2 migration](docs/kctx/migration-hardening.md)
- [Tracked fixes and local diff review: rationale and kernel boundary](docs/kctx/review-feature-requests.md)
- [Provider-neutral asset catalog design](docs/kctx/catalog-design.md)
- [Full requirements and Q/D scenario registries](docs/kctx/handover.md)

The Rust design keeps Dolt outside the calculus, manages it as a pinned companion
rather than embedding Go through FFI, and preserves the same semantic and
operational qualification gates. Vendor-specific source names belong in catalogs
and providers, not the logical kernel.
