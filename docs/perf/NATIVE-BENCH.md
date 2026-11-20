# NATIVE-BENCH — S0 native-backend prototype evidence (V2-S0-D)

**Date:** 2026-11-20 · **Commit:** builder/v2-s0-roadmap-lock (this tree)
**Stage:** S0 prototype evidence for the S2 gate (NEXT.md §2). NOT the
official S2 gate run — that is V2-S2-B, after a real MIR→CLIF frontend
exists.

## What was measured

`examples/native-jit/` (standalone crate, own lockfile — the main crate
stays zero-external-crates) compiles two kernels through a Cranelift JIT
(cranelift 0.137.3, `opt_level=speed`) and benchmarks them against
LLVM-optimized Rust implementations of the same semantics **in the same
process**:

1. `fib(25)` — recursive i64, the call-heavy gate kernel.
2. `axpy_kernel` — `p[i] = p[i]*a + b` over 1,000 f64 × 500 iterations.
   This is the **n-body-morphic proxy** for S0: a flat, memory-bound f64
   array loop. The real n-body kernel (pairwise forces + sqrt) is the
   V2-S2-B official gate — the proxy was chosen because it exercises the
   same codegen path (load/fmul/fadd/store over arrays) without hand-rolling
   150 lines of CLIF before the toolchain path is proven.

Cross-backend **bit parity** is asserted in-process before timing: the
Cranelift kernel and the LLVM Rust kernel produce identical f64 bits after
500×1,000 updates (deterministic-arithmetic contract, brief §8.14).

The LLVM `fib` argument is `std::hint::black_box`-wrapped: without it LLVM
folds the whole recursion into a compile-time constant (observed at
"24 ns" before the fix) and the comparison is meaningless.

## Environment

- Machine: `Intel(R) Xeon(R) Processor` (sandbox VM, shared host — expect
  noise), Linux x86_64
- rustc/cargo 1.100.0 (stable), main-crate release profile unchanged
  (`opt-level=3, lto=false, codegen-units=16`)
- cranelift-codegen/frontend/jit/module/native 0.137.3

## Commands

```
cd examples/native-jit && cargo build --release
./target/release/native-jit                          # 3 recorded runs
cd ../.. && cargo build --release                    # main crate
./target/release/operon run scripts/bench/fib25.op   # same-machine VM point
```

## Exact outputs

Three consecutive runs of `./target/release/native-jit`:

```
=== bench run 1 ===
# parity: fib(25)==75025 OK; axpy 500x1000 f64 updates bit-identical across Cranelift and LLVM
fib(25)  cranelift median =    478126 ns
fib(25)  llvm-rust median =    182353 ns
fib(25)  ratio            =     2.622 x   (S2 gate: <= 2.0)
axpy      cranelift median =    194400 ns  (500 x 1000 f64 updates)
axpy      llvm-rust median =     62664 ns
axpy      ratio            =     3.102 x   (S2 gate: <= 2.0; LLVM may auto-vectorize this loop)
GATE-S2-PROTOTYPE fib: FAIL  axpy: FAIL

=== bench run 2 ===
fib(25)  cranelift median =    477500 ns
fib(25)  llvm-rust median =    181976 ns
fib(25)  ratio            =     2.624 x   (S2 gate: <= 2.0)
axpy      cranelift median =    190054 ns
axpy      llvm-rust median =     62661 ns
axpy      ratio            =     3.033 x   (S2 gate: <= 2.0; LLVM may auto-vectorize this loop)
GATE-S2-PROTOTYPE fib: FAIL  axpy: FAIL

=== bench run 3 ===
fib(25)  cranelift median =    474402 ns
fib(25)  llvm-rust median =    181078 ns
fib(25)  ratio            =     2.620 x   (S2 gate: <= 2.0)
axpy      cranelift median =    190011 ns
axpy      llvm-rust median =     63908 ns
axpy      ratio            =     2.973 x   (S2 gate: <= 2.0; LLVM may auto-vectorize this loop)
GATE-S2-PROTOTYPE fib: FAIL  axpy: FAIL
```

Same-machine VM point (this tree, `operon run scripts/bench/fib25.op`,
3 runs, python wall-clock timer around the whole process — startup included):

```
run1: 103.2 ms   run2: 103.8 ms   run3: 104.1 ms   median: 103.8 ms
```

## Reading the numbers

| kernel | VM (this tree, process incl. startup) | Cranelift JIT | LLVM -O Rust | JIT / LLVM |
|---|---|---|---|---|
| fib(25) | 103.8 ms | ~477 µs | ~182 µs | **2.62–2.64×** |
| axpy 500×1000 f64 | — | ~190 µs | ~63 µs | **~3.0×** |

1. **The v2 direction is confirmed at the architecture level:** on the same
   machine, the existing engine needs ~104 ms for fib(25); the Cranelift
   baseline JIT does it in ~0.48 ms — a **~217×** leap. The "one typed MIR +
   compiled backends" thesis is worth building on.
2. **The S2 2× gate is NOT met at prototype level** (2.6× on fib, 3.0× on
   axpy). Per NEXT.md §6 this halts feature expansion on the backend path
   until the investigation lands: where the gap lives (call sequence,
   prologue/epilogue, missing fastcall tricks, no auto-vectorization) and
   whether the gate as written applies to the DEV backend (Cranelift) or the
   RELEASE backend (LLVM). Evidence points at a scope decision, not a
   dead architecture: LLVM's axpy win is auto-vectorization (an elementwise
   loop; Cranelift does not vectorize), and fib is call-overhead-bound where
   LLVM pairs of leaf calls fold aggressively.
3. **axpy is a pessimistic proxy for n-body:** elementwise loops vectorize
   trivially under LLVM; the real n-body inner loop carries accumulations
   and is harder to vectorize, so its gap is expected to be smaller. The
   official V2-S2-B run decides, not this proxy.
4. Run-to-run variance is small (Cranelift ±1%, LLVM fib ±0.3% after the
   black_box fix; one earlier run measured LLVM fib at ~153 µs before
   `iter_mut` reshuffling — treat the LLVM side as having a ±15% noise band
   on this shared-host VM).

## Consequences recorded in NEXT.md

- V2-S0-D: DONE (toolchain path proven end-to-end: declare → CLIF → JIT →
  call, with cross-backend bit parity).
- NEW V2-S2-C (READY, blocking S2): backend investigation — profile the fib
  gap, test Cranelift settings/ABI knobs, define whether the 2× gate binds
  the dev JIT or the release LLVM tier, and re-run the gate on the real
  n-body kernel. No feature work past the gate until this closes.
