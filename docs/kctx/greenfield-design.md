# kctx greenfield design — a rebuild for other people

Date: 31 October 2026. Question asked: *if kctx were rebuilt from scratch and
made available for other people — what language, what shape, what
distribution?* This is a design position, not a commitment to abandon the
Python implementation; the Python core remains the production system and the
Lean calculus remains the semantic authority either way.

## TL;DR

**Rust, single static binary, workspace of small crates, the Lean calculus
compiled to a decision kernel behind a stable crate boundary, Git for
authored assets, Dolt (or SQLite in the small case) for the relation/graph
projection, agents served over a JSONL protocol with the same envelopes the
conformance suite already uses.** The calculus — not the language — is the
product; the Rust rewrite is a faster, safer *host* for the same proved
verbs, re-qualified against the same Lean reference before anything ships.

## Why Rust (and not Go, not Python)

| Option | Verdict | Reasoning |
| --- | --- | --- |
| **Rust** | **yes** | This is already the house language: `gripsack` (14 crates) and `strop` (21 crates) share conventions — `-core`/`-fs`/`-trace` crate splits, `edition` pins, compose-gated verification, Verus/TLA+ alongside, `rustls`-only, static musl binaries with `install.sh` + homebrew tap + self-update. Distribution to "other people" is a solved problem here; every dependency choice is pre-litigated. |
| Go | no | Fine for CLIs, but the house has no Go toolchain investment, no shared CI patterns, and no proof story; we would rebuild conventions from zero. |
| Python (stay) | keep as the reference host | The typed core we just built *is* the semantic definition of record and the conformance twin; a rewrite must displace it, not duplicate it. Python stays until the Rust core passes the same conformance suite and the same gate discipline (handover §15.1 says exactly this). |

## The shape

```mermaid
flowchart LR
    subgraph authored["Git (ordinary files)"]
        md[Markdown notes / dossiers]
        cfg[policies, schemas, migrations]
    end
    subgraph engine["kctxd core (Rust)"]
        sem[decision kernel\n(sealed, versioned)]
        idx[extractor + graph projection]
        q[typed query engine\nSQL over Dolt / SQLite]
    end
    subgraph agents["any agent, any language"]
        cli[kctx CLI]
        jl[JSONL protocol\nsame envelopes as today]
    end
    md --> idx --> q
    sem --> q
    q --> cli & jl
```

### Crate layout (mirroring the house style)

| Crate | Role | Notes |
| --- | --- | --- |
| `kctx-core` | The decision kernel: claims, evidence, derivations, freshness, workflow transitions | A **mechanical translation of `formal/Kctx` + `src/kctx/semantics`** — same names, same rejection order, same wire format. No new semantics, ever. |
| `kctx-wire` | Positional-array JSON codec, envelopes, `SEMANTIC_VERSION` | Byte-compatible with `formal/Kctx/Codec.lean` and `kctx/semantics/wire.py`. |
| `kctx-store` | Content-addressed record store; conditional writes; journal | The T20/T21 protocol made real; SQLite in the small case. |
| `kctx-graph` | Extractor + projection to Dolt (or SQLite when Dolt is absent) | Generation manifests, pinned reads, parity checks — the M2 shadow semantics, hardened per handover §9. |
| `kctx-git` | Snapshot enumeration, worktree identity, `git archive` audit | `git2 default-features = false` (strop rule). |
| `kctx-trace` | Structured operation logging | House pattern (`gripsack-trace`, `strop-trace`). |
| `kctx-cli` | Clap subcommands mirroring today's surface (`context`, `check`, `admit`, `uses`, `graph`, `doctor`…) | Stable exit codes `0/2/3/1` carried over verbatim. |
| `kctxd` (optional) | Long-lived query server speaking the JSONL protocol | Only if measured agent overhead justifies it (handover G15). |

### What stays exactly as designed

- **The Lean calculus is the authority.** A Rust kernel is a third host of the
  same semantics; the conformance harness grows a third column (Lean | Python
  | Rust) and all three must agree on every case before any Rust release.
  "Faster language inherits no proof status" is already written into the
  handover (§15.1); the theorem registry covers the *model*, and the Rust
  core is qualified by conformance, not by hope.
- **Git for authored assets; Dolt for relations; evidence by exact identity.**
  The storage-authority table in `docs/kctx/handover.md` §2.1 is
  implementation-independent and carries over unchanged.
- **One readiness predicate, one TTL convention, one rejection order.** These
  are now proved contracts; the rewrite inherits them as wire-level
  invariants with cross-implementation tests.

### The one thing Rust uniquely enables

A **sealed kernel crate with `#[no_std]`-friendly pure functions and zero
I/O**, plus exhaustive `match` over the rejection/transition enums — the
compiler then enforces what the Python side enforces by review. Add
`proptest` on the same generators the conformance corpus uses, and mutation
testing (flip a TTL boundary, drop a footprint dep — the deliberate-mutation
suite from handover §13.1) as a CI gate, exactly like strop's
`check_mutants.py`.

## Distribution (copying the house playbook)

1. Static musl binaries (Linux x86_64/aarch64, macOS arm64) via
   `install.sh` + homebrew tap — the strop channel (`strop.dev/install.sh`,
   `stropdev/tap`) is the template, including "installer refuses unsupported
   targets rather than guessing".
2. `cargo install kctx-cli --locked` for the Rust-native audience (gripsack
   publishes to crates.io the same way).
3. **Agents don't install anything** where possible: the JSONL protocol means
   any harness can drive the kernel over stdin/stdout with the versioned
   envelope, and `kctx doctor --json` reports exact kernel/wire/store
   versions the way `kb doctor` is specified to in the handover.
4. Proof artifacts never ship: `docker compose --profile formal` builds and
   audits them (gripsack's `model`/`tlaps`/`verify` services are the
   template), and releases cite the `proof-report.json` digest.

## Qualification discipline (unchanged, non-negotiable)

The handover's gates apply to the rewrite unchanged: conformance must pass on
every case; a missing reference column fails the job; deliberate mutations
must be caught; adoption of any new backend (Dolt) still needs the measured
benefit. The greenfield risk is not the language — it is *drift from the
proved semantics*; the three-host conformance matrix is the control for
exactly that.

## If I had to start from zero tomorrow

1. Write the calculus first (this exists: `formal/Kctx`), freeze the wire
   format (this exists: `Codec.lean` + `wire.py`), and the case corpus (this
   exists: `tests/conformance/cases.jsonl`).
2. Implement `kctx-core` + `kctx-wire` in Rust against those artifacts; run
   the three-way matrix until green.
3. Grow outward: `kctx-store` (journal + conditional writes), `kctx-git`,
   then `kctx-graph` behind the shadow-mode rules, then the CLI.
4. Ship the binary; the Python core retires when — and only when — the
   Rust host has passed every gate the Python host passes today.
