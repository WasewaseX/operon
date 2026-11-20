# ROADMAP-MIGRATION — M100 (W-IDs) → Operon v2 (V2-IDs)

**Date:** 2026-11-20 · **Authority:** [NEXT.md](NEXT.md) and the v2 design
brief. **Rule:** every old task gets exactly one disposition — KEEP (carry
forward as-is), MODIFY (goal survives, mechanism changes per v2), DEFER
(postponed behind a gate, with the gate named), RETIRE (rejected by v2 §26 /
§32 with the recorded rationale). Historical statuses and evidence in
`TODO-100.md` and the vault board are preserved untouched; this file only
re-points future work. `collab/TASKS.md` / `collab/ROADMAP-100.md` live in
the external vault repo (out of scope for this in-repo migration — the vault
board is frozen as-of the migration commit; keepers re-sync when v2 tasks
start landing there).

## Quick reference — v2 stage gates

S0 design lock (this PR) → S1 typed-MIR parity → S2 native 2× gate →
S3 networks + JS backend (Solid band) → S4 cells + replay → S5 placement +
full-stack Todo. See NEXT.md §2.

## Dev-1 block, W001–W033 (language core)

| W | topic | → v2 | disposition |
|---|---|---|---|
| W001 | optional type annotations | feeds S1: types become trusted in the strict core subset; gradual checking stays for legacy mode | MODIFY (V2-S1-A) |
| W002 | ADTs + match v2 | done historically; carried into typed MIR as sum types + exhaustive match | KEEP |
| W003 | generics | dictionary-passing in dev, monomorphize only what closed-world release analysis proves (v2 §16) | MODIFY (V2-S2-A) |
| W004 | traits | kept; trait methods carry explicit effect annotations at the boundary (v2 §12.4) | MODIFY (V2-S4-A) |
| W005 | let/const/mut | superseded by move-by-default ownership + explicit copy + scoped views (v2 §11) | MODIFY (V2-S1-A) |
| W006 | Option/Result + `?!` | kept as-is (error model is a named preserved asset) | KEEP |
| W007 | error tracebacks | kept (error model + stack chains asset) | KEEP |
| W008 | debugger / DAP | kept (LSP/DAP asset); new: step across MIR interpreter + JIT frames | KEEP |
| W009 | bytecode VM (OIR1) | demoted to reference engine alongside the MIR interpreter; OIR1 stops being the compiler target when MIR parity lands | MODIFY (V2-S1-B) |
| W010 | disassembler | retargeted: MIR dump first, OIR1 dump stays for the legacy lane | MODIFY (V2-S1-B) |
| W011 | optimization pipeline | passes move to MIR level, parity-gated by the differential harness; existing VM passes stay for the reference engine | MODIFY (V2-S2-A) |
| W012 | JIT | repointed: Cranelift baseline JIT per function on first call + hot patching (v2 §12/§16); the old generic "JIT" task is V2-S2-A | MODIFY (V2-S2-A) |
| W013 | memory-cycle strategy | generation-checked arena handles for graphs/cycles (v2 §11); Rc<RefCell> scripting model stays only in legacy mode | MODIFY (V2-S1-A) |
| W014 | memory model spec | rewritten by the v2 ownership/views spec (NEXT.md §3 rules 1–6) | MODIFY (V2-S1-A) |
| W015 | channels + select | mailboxes are the v2 primitive (cells §13); channels stay as a std library over mailboxes | MODIFY (V2-S4-A) |
| W016 | async model | superseded by inferred suspension with visible call-site markers; no coloring; declarations uncolored (v2 §12) | MODIFY (V2-S4-A) |
| W017 | structured concurrency | kept — the deterministic scheduler/scope contract is a named asset | KEEP |
| W018 | task cancellation | cancellation kills the cell and frees its cell-owned region; ordinary values still die at scope end (v2 correction §8.2) | MODIFY (V2-S4-A) |
| W019 | modules → packages | kept (package asset) | KEEP |
| W020 | package manager CLI | kept | KEEP |
| W021 | registry | kept | KEEP |
| W022 | operon.toml manifest | becomes the genome artifact: caps, deps, config, metadata + capability declarations (v2 §7) | MODIFY (V2-S4-A) |
| W023 | lockfile | kept; lockfile additionally records capability differences of dependencies (v2 §15) | MODIFY |
| W024 | visibility model | kept | KEEP |
| W025 | dotted namespaces | kept; module = operon naming retained | KEEP |
| W026 | typed collections | kept; feeds strict-core std | KEEP |
| W027 | stdlib breadth | kept (self-hosting continues) | KEEP |
| W028 | unicode depth | kept; v2 adds the UTF-8/UTF-16 JS boundary contract (NEXT §3 rule 14) | KEEP |
| W029 | bytes type | kept | KEEP |
| W030 | raw/multiline/byte strings | kept | KEEP |
| W031 | numeric literal forms | kept; Int stays checked 64-bit across tiers (v2 §8.11) | KEEP |
| W032 | BigInt/Decimal | kept as library; JS-target cost is measured per brief §17 before any reliance | KEEP |
| W033 | date/time types | kept; time access is capability-routed | KEEP |

## Dev-2 block, W034–W065 (tooling, truth, ecosystem)

| W | topic | → v2 | disposition |
|---|---|---|---|
| W034 | serialization trait | kept; S5 adds the server-only-type rule (no serializer → compile error on browser-bound leak) | MODIFY (V2-S5-A) |
| W035 | macros | deterministic, cacheable compile-time evaluation on the same MIR; no external proc-macro processes (v2 §16) | MODIFY (V2-S3-A) |
| W036 | hard core/bio boundary | kept and strengthened: the §26 rejected-ideas list is binding | KEEP |
| W037 | Total Grammar semantic contract | strict compilation rejects invalid code; repair becomes fix/LSP-only tooling (v2 §32). Contract doc rewritten for the strict core | MODIFY (V2-S1-A) |
| W038 | repair explanation mode | kept as tooling documentation | KEEP |
| W039 | AST dump | kept | KEEP |
| W040 | IR/bytecode dump | retargeted to MIR dump (with OIR1 retained for legacy) | MODIFY (V2-S1-B) |
| W041 | check rework | kept; strict mode makes findings rejections in the new subset | KEEP |
| W042 | static analysis depth | kept; network/ownership checks extend it | KEEP |
| W043 | wrong-arity detection | kept | KEEP |
| W044–W046 | LSP depth/repairs | kept (LSP asset); quick-fixes become the only repair surface | KEEP |
| W047 | formatter config | kept | KEEP |
| W048 | lint | kept | KEEP |
| W049–W052 | test runner, property testing, fuzzing, coverage | kept (verification assets) | KEEP |
| W053–W055 | doc stats/versioning/keyword count | kept | KEEP |
| W056–W058 | README/docs truth passes | kept; the v2 pointer block on README.md is part of this PR | KEEP |
| W059–W060 | CI blocking/release smoke | kept | KEEP |
| W061–W062 | distribution/LSP versioning | kept | KEEP |
| W063 | language compatibility policy | kept; v2 breaking changes (e.g. suspension gained) reported by interface diff per v2 §12 | MODIFY |
| W065 | automated migrator | kept; absorbs the retired `.rna` runtime role as pure source tooling | MODIFY |

## Dev-3 block, W066–W100 (contracts, safety, release engineering)

| W | topic | → v2 | disposition |
|---|---|---|---|
| W066 | .cell schema | flat `.cell` replaced by typed profiles + manifest (v2 §32); schema work feeds the profile types | MODIFY (V2-S4-A) |
| W067–W068 | .rna edit model/safety | runtime `.rna` patching retired from the language core (v2 §26); survives only as codemod tooling merged into the W065 migrator | RETIRE (tooling fold-in) |
| W069–W070 | module resolution/import diags | kept | KEEP |
| W071 | hot reload | dev JIT + typed state schema-diff migration; impossible migration → cell restarts under supervisor (v2 §12/§17) | MODIFY (V2-S4-B) |
| W072 | operon watch | kept | KEEP |
| W073–W075 | doc generator/doc comments/example docs gate | kept | KEEP |
| W076 | embedding API | embedding becomes cells/processes over a wire protocol; unsafe stays out of user reach | MODIFY (V2-S4-A) |
| W077 | C ABI | kept — the only FFI surface; beyond it is a non-goal | KEEP |
| W078–W079 | python bridge contracts | kept as a host capability (substrate statement stays true); never a semantic tier; the oracle's role is re-scoped per NEXT §4 | KEEP |
| W080 | native C/C++ FFI | heavy FFI beyond the C ABI is a v2 non-goal | RETIRE |
| W081 | C++ kernel boundary guard | kept (build infrastructure) | KEEP |
| W082–W084 | perf gating/real-program benchmarks/startup | kept; native gates (NEXT §2) join the perf workflow after S2 | KEEP |
| W085 | standalone executable | release path = whole-program LLVM closed-world binaries (v2 §16); the old generic task folds into the release tier | MODIFY (V2-S2-A+) |
| W086–W088 | build contract/bundle/reproducible builds | kept | KEEP |
| W089 | randomness determinism | kept; RNG only through capabilities (v2 §17) | KEEP |
| W090 | floating-point determinism | kept; identical overflow/FP semantics across tiers is a v2 invariant (v2 §8.14) | KEEP |
| W091–W092 | bio semantics separation/modeling contract | kept; biology survives only where the compiler gains information (declared edges, specialization, cell typestate) | MODIFY |
| W093 | scientific validation layer | kept | KEEP |
| W094–W095 | graph export/regulation visualizer | kept as tools; visualizer retargets to compiler-visible network edges when S3 lands | MODIFY (V2-S3-A) |
| W096–W098 | profiler/memory/thread profilers | kept; fuel evolves into the portable budget unit (v2 §31) | MODIFY |
| W099–W100 | security automation/threat model | kept; THREAT-MODEL gains the v2 capability-narrowing and wire-protocol plugin sections | KEEP |

## Retired by the v2 brief even if the old queue never listed them

Dynamic analog GRN edges as core semantics (stay as a deprecation-window
std module until S4), methylation counters as language feature, runtime
self-modifying evolution, quorum-sensing keyword, `homeostasis` keyword,
compiling UI to WASM, the playground's duplicate interpreter as an
independent semantics, the Python oracle as a third independent semantics,
keeping `gene` for ordinary functions in the strict core.

## Unavoidable conflicts found during mapping (call-outs)

1. README.md still describes the VM as a future v3 item while v2 makes it a
   reference engine (brief §3 doc-drift finding) — README gets a pointer
   block now; full rewrite lands with the v2 README pass.
2. docs/VM.md still describes a compile.rs that does not exist under src/
   (brief §3 finding) — frozen as historical record; the MIR design note
   (V2-S1-B deliverable) becomes the current pipeline description.
3. The M100 iron rule "differential harness ALL MATCH before merge" is
   retained and extended: new lanes (MIR interpreter, later JIT/native)
   must match before merge, per NEXT §7.
4. TODO-100's "invariants red = stop everything" applies unchanged to v2
   gates; a missed S2 gate stops feature work by design (NEXT §6 rule).
