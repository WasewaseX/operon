# NEXT — canonical active plan (Operon v2)

**Status: CANONICAL.** This file is the single active roadmap for Operon.
It supersedes `TODO-100.md` (the M100 program), which is archived in place
with a superseded banner — see [ROADMAP-MIGRATION.md](ROADMAP-MIGRATION.md)
for the old-task → new-plan mapping. History is preserved; nothing was
deleted.

**Source of authority:** *"Operon: Revised Language Design and Agent
Execution Brief"* (owner-provided, 2026-11-20). Where an older document
(README, SPEC.md, docs/spec/*, TODO-100.md) contradicts this file on
architecture or priorities, this file wins until v2 lands the change and
the older document is updated in the same PR.

Task protocol follows CONTRIBUTING.md and `.github/collab/LOCKS.md`:
`READY → CLAIMED → IN_PROGRESS → BLOCKED / VERIFY → DONE`, one claimant,
PR-only landings, `Task-ID:` + `Paths:` in every PR body.

---

## 1. Direction in one paragraph

One typed source, compiled to **one typed MIR**, expressed differently per
execution context: a Cranelift baseline JIT for development (per-function
compile on first call, hot patching), whole-program LLVM for release
binaries, and a MIR interpreter as the semantic reference and compile-time
evaluator. Users learn four concepts: **ownership (with scoped views)**,
**effects (suspension, I/O, DOM, placement, capabilities)**, **cells**
(mailbox actors with budgets), and **networks** (declared, statically
shaped dependency graphs with dynamic instances). The UI compiles to
JavaScript; WASM is reserved for compute-heavy pure islands. Biology is
kept only where it gives the compiler or runtime real information (an
operon is still a good name for a module; declared regulation edges are
compiler-visible structure; analog Hill edges, methylation counters,
runtime `.rna` patching and decorative keywords are out of the core).

The performance expectation (1.0–1.3× Rust typical, parity on numeric
kernels) is a **hypothesis under test**, not a claim. Gates below decide.

## 2. Stage plan and gates

| stage | scope | gate (all gates need recorded commands + outputs) | status |
|---|---|---|---|
| S0 | Lock the design: this file, migration map, supersede old roadmap; write the view-rule exercise; scaffold typed MIR + interpreter; minimal Cranelift prototype for fib/n-body | all S0 artifacts merged; exercise report published; prototype numbers recorded | **DONE (2026-11-20)** |
| S1 | Strict core subset → typed MIR → interpreter on MIR; differential parity against the existing engines on the existing corpus (`tests/differential/`, vm_parity lane) | **100% parity on the S1 corpus slice** (bootstrap/harness.py + vm lane stay green; new MIR lane added to the harness) | READY |
| S2 | Minimal Cranelift backend for numeric kernels: recursive fib and n-body | **compiled fib and n-body within 2× of optimized Rust `-O`** on the same machine, same OS, recorded in docs/perf/NATIVE-BENCH.md. If the gate misses: STOP feature expansion, investigate/reconsider the backend before anything else. **S0 prototype first evidence (2026-11-20): fib 2.62×, axpy proxy 3.0× — gate NOT met at prototype level; backend investigation opened as V2-S2-C; no feature expansion past this line until it closes** | BLOCKED on V2-S2-C |
| S3 | Compiler-visible networks + JavaScript backend + Todo app | js-framework-benchmark band vs Solid (10k keyed rows explicitly benchmarked; realistic target is parity, not a win); bundle size recorded | BLOCKED on S1/S2 |
| S4 | Cells, inferred suspension with visible call-site markers, scheduler port onto cells, deterministic replay | record/replay one cell under load; replay is bit-exact; logging overhead measured | BLOCKED on S3 |
| S5 | `on Server` / `on Browser` placement, RPC codegen (`Result<T, NetError>`, timeout, cancel, schema hash), SSR resume, full-stack Todo from one source | full-stack Todo runs from one source; server-only type leaking into a browser cell is a compile error (negative test) | BLOCKED on S4 |

S1 and the minimal S2 proof run together or tightly coupled — the point is
to test the two architecture-killing risks (view model, native codegen
viability) before building an extensive MIR.

Longer-term performance targets (post-S2, from brief §22 — never a
substitute for the gate above): fib/call-heavy within 1.1× of Rust;
n-body and matmul within ±5%; HTTP hello-world vs Axum; cold/incremental
compile time vs Cargo on a same-size project; memory per cell at 1M cells.
Overflow semantics must be identical across every tier; kernels use
explicit wrapping ops; benchmarks measure both checked and wrapping paths.

## 3. Binding invariants (violating any of these is a design bug, not a style choice)

**Ownership and views**
1. Unique ownership, move by default, explicit copy. No silent copies.
2. Scoped views are second-class. A view-holding struct is itself
   non-storable and non-returnable. A returned view may be tied by elision
   to exactly one argument; ambiguous sources are compile errors; rare
   cases use `from(param)`.
3. **Views never cross a suspension point.**
4. This is honestly "Rust with second-class borrows and scoped views" —
   NOT a lifetime-free language, and never a claim of stronger no-alias
   guarantees than Rust. Std provides swap/split helpers for the cases
   (e.g. `arena[a]` vs `arena[b]`) the checker cannot prove disjoint.
5. Values die at scope end. A cell-owned region dies at cell termination;
   regions are an allocator strategy (e.g. per-request bump), not the
   general memory story. Cycles/graphs use generation-checked arena
   handles. Frozen shared data is immutable + atomically refcounted.
6. `unsafe` exists only inside std and the FFI boundary. Users write safe
   code. `Shared<ConcurrentMap>` is a std intrinsic.

**Effects and suspension**
7. Declarations stay uncolored; the compiler infers suspension; every
   suspending call site shows a visible marker. A library function gaining
   suspension is a breaking interface change (reported by interface diff).
   Trait methods and function pointers carry explicit effect annotations.
8. Capabilities are inferred effects, declared at entry points and in the
   manifest — never threaded manually through every function. Placement is
   inferred from effects; only entry points and RPC boundaries state
   placement.
9. A cell runs to completion between suspension points; reentrancy is
   JS-like and documented.

**Cells, networks, determinism**
10. Cells are share-nothing mailbox actors: region + mailbox + budget +
    capability set + lifecycle. Values move or freeze across boundaries.
    The deterministic FIFO scheduler, virtual clock and structured-scope
    contract are retained assets; cancellation kills the cell.
11. Networks have declared, static, compiler-visible dependency edges;
    dynamic analog levels (Hill functions on name-keyed state) are out of
    the core. Derived values are pure and synchronous; feedback passes an
    explicit one-step delay; async data is a resource node with typed
    loading/ready/error state driven by a cell. Network types are static,
    instances dynamic; keyed collections use runtime-tracked per-key
    dependencies and get no assumed performance win.
12. Determinism is the dev/test mode (deterministic hash iteration,
    no pointer-derived values, time/randomness only through capabilities).
    Production uses record/replay of message order + I/O results.

**Targets**
13. UI compiles to JavaScript (direct DOM access). WASM only for
    compute-heavy pure islands behind a typed bridge. DOM glue stays JS.
14. Int is checked 64-bit everywhere; range analysis may lower to a plain
    JS number only when proven safe; BigInt costs are measured, not guessed.
    Strings are UTF-8 with byte-indexed APIs; JS's UTF-16 boundary is
    handled by explicit conversion at the platform edge.
15. Plugins are separate cells or processes over a wire protocol — never
    dynamic libraries. Whole-program analysis applies to closed-world
    release binaries only, never the dev loop. Dev generics use dictionary
    passing; release monomorphizes only what closed-world analysis proves.
    Macros are deterministic, cacheable compile-time evaluation on the
    same MIR — no arbitrary proc-macro processes.

**Non-goals (do not reopen):** embedded/bare-metal, kernel development,
GPU work, dynamic-library plugins, heavy FFI beyond the C ABI, systems
programming as a current target. Explicitly rejected ideas (brief §26 — do
not reintroduce): dynamic analog regulation edges, a `homeostasis`
keyword, runtime self-modifying "evolution", runtime `.rna` text patching,
a quorum-sensing keyword, UI-to-WASM, lowering the 25 bio keywords onto
five laws, methylation counters as a language feature.

## 4. Assets preserved (carry forward, do not regress)

Parser diagnostics + fix-its (E1xxx/E2xxx, JSON), LSP, DAP, fmt, lint,
doc generator, profiler/Chrome-trace output; package manager, lockfile,
registry; capability model (default-deny) narrowed **per cell**; the
differential harness and parity discipline; the deterministic scheduler
contract (virtual clock, structured scope, cooperative cancel); the error
model and stack chains; security/red-team suite (109 contained payloads);
`std/biocore` (evolving into compiler-visible network support);
`build --variant` (evolving into typed profiles); fuel ceilings (evolving
into a portable cost unit — cost per source operation, not per VM
instruction); `operon.toml` manifest work (becoming the genome artifact:
caps, deps, config, metadata).

Preserve verification coverage while **reducing duplicated semantics**:
the tree-walk interpreter, the VM, the Python oracle and the playground's
JS interpreter must not remain four independent semantic implementations.
Around the typed MIR: interpreter on MIR = semantic reference; the Python
oracle and playground stop being independent semantics (playground is
replaced by the real JS backend; the oracle becomes an independent
checker of the shared MIR where useful). VM operator semantics currently
delegating to the tree-walk (parity by construction) get real MIR-backed
parity.

## 5. Removals / demotions schedule (testable migrations only)

| when | change |
|---|---|
| S1 | `fn` becomes the ordinary-function keyword in the strict core subset (`gene` remains parsed for the legacy corpus until S1 parity is frozen) |
| S1→S2 | strict execution rejects invalid programs; runtime Total Grammar repair becomes `operon fix` / LSP quick-fixes only (typo-tolerant *tooling*, never silent runtime semantics) |
| S2 | OIR1/vm.rs keeps reference-engine status; new optimization passes land on MIR, parity-gated |
| S3 | playground's duplicate interpreter replaced by the real JS backend output |
| S4 | flat `.cell` config replaced by typed profiles + manifest (profiles derived from `build --variant`); dynamic GRN analog levels removed from the core (remain available as a std library module during deprecation, then deleted) |
| S5 | Python oracle demoted from third semantics to differential checker of the shared MIR |

No working functionality is removed before its replacement and regression
coverage exist.

## 6. Task queue (v2 IDs; old W-IDs map in ROADMAP-MIGRATION.md)

| id | task | status |
|---|---|---|
| V2-S0-A | docs/design/NEXT.md canonical; supersede TODO-100.md; migration map | DONE (this PR) |
| V2-S0-B | 500-line view-rule exercise + report (docs/design/view-exercise/, docs/design/VIEW-EXERCISE.md) | DONE (this PR) |
| V2-S0-C | typed MIR scaffold + interpreter on MIR + unit tests (src/mir/) | DONE (this PR) |
| V2-S0-D | minimal Cranelift prototype, fib + n-body proxy, native crate examples/native-jit/ (own Cargo.toml — keeps the main crate zero-external-crates); record docs/perf/NATIVE-BENCH.md | DONE — prototype runs, bit-parity OK, gate ratio 2.6–3.1× recorded |
| V2-S1-A | define the S1 strict-core subset (grammar slice, typed AST slice) written as a spec section | READY |
| V2-S1-B | lower strict-core AST slice → typed MIR; wire the MIR interpreter into the differential harness as a third lane on a corpus subset | READY |
| V2-S1-C | corpus parity: pick the S1 corpus slice from tests/differential/, record pass/fail per file | READY |
| V2-S2-A | Cranelift backend promoted from examples/native-jit into the toolchain (`operon build --jit`), dictionary-passing generics, no LLVM in dev loop | READY, gate S2 |
| V2-S2-B | fib + n-body official gate run vs Rust `-O` on pinned hardware, checked + wrapping arithmetic variants | READY, gate S2 |
| V2-S2-C | **backend investigation (opened by S0 evidence, blocking S2):** profile the fib gap (2.62×), test Cranelift ABI/setting knobs, decide whether the 2× gate binds the dev JIT or the release LLVM tier, re-run on the real n-body kernel. No feature expansion past this line until closed | READY |
| V2-S3-A | network IR: declared edges, derived-value purity, one-step delay primitive; compile network type → straight-line update fn + slot array | READY, gate S3 |
| V2-S3-B | JS backend emitting DOM-direct code; Todo app; krausest rows + bundle size vs Solid | READY, gate S3 |
| V2-S4-A | cell runtime on the existing scheduler (mailbox, budget, caps per cell, lifecycle); inferred suspension with visible markers | READY, gate S4 |
| V2-S4-B | deterministic replay (message order + I/O results); state schema-diff migration on hot patch | READY, gate S4 |
| V2-S5-A | placement types/effects (`on Server`/`on Browser`), RPC stub codegen with schema-hash handshake | READY, gate S5 |
| V2-S5-B | SSR: serialize typed state, resume client-side without rerunning code; full-stack Todo | READY, gate S5 |

Rule from the brief: do not expand features past a missed gate. If S2's
2× gate misses, the only allowed next task is investigating the backend.

## 7. Evidence policy

- Every gate claim carries: exact command, exact output, machine/OS note,
  commit hash. No gate is claimed green from reasoning.
- Benchmarks continue to land under `docs/perf/` (BARS.md stays the VM-era
  record; native-era numbers go to NATIVE-BENCH.md).
- Differential/parity runs state lane counts ("N/N MATCH, 0 diverge").
- Research is capped at ~20% of any session's effort; the brief's
  repository review is the trusted baseline — revalidate only the files a
  slice actually touches.

## 8. Kill criteria (what would invalidate the architecture)

1. The view exercise (or the S1 checker on real code) needs `from(param)`
   more than occasionally → the reduced-lifetime premise fails; report
   openly, do not quietly redesign.
2. S2 native gate misses 2× → reconsider the backend before any feature.
3. S1 parity gaps that persist after narrowing the subset → MIR redesign.
4. Network compile-to-update-fns cannot match Solid within the benchmark
   band → re-scope the frontend claims (parity is the ceiling by design).
