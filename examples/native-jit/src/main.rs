//! native-jit — S2 prototype (V2-S0-D, docs/design/NEXT.md §2).
//!
//! Compiles two kernels through a Cranelift JIT in-process and benchmarks
//! them against LLVM-optimized Rust implementations of the SAME semantics,
//! in the same process, on the same machine:
//!
//! 1. `fib` — recursive i64, the call-heavy gate kernel (brief §22).
//! 2. `axpy_kernel` — a memory-bound f64 array loop (`p[i] = p[i]*a + b`
//!    over n elements × iters). This is the n-body-MORPHIC proxy: the real
//!    n-body kernel (pairwise forces + sqrt) is the V2-S2-B official gate
//!    once a MIR→CLIF frontend exists; this prototype proves the toolchain
//!    path end-to-end and produces the first honest ratios.
//!
//! Cross-backend parity is checked in-process: the Cranelift kernel and the
//! Rust kernel must produce bit-identical f64 results (the deterministic
//! arithmetic contract from the brief, tested where it hurts — across
//! code generators).
//!
//! Run:
//!   cd examples/native-jit && cargo run --release
//! Gate (S2 prototype level): compiled kernel within 2x of the LLVM Rust
//! kernel. Real n-body gate: V2-S2-B.

use std::time::Instant;

use cranelift_codegen::ir::condcodes::IntCC;
use cranelift_codegen::ir::types;
use cranelift_codegen::ir::{AbiParam, BlockArg, InstBuilder as _, MachMemFlags};
use cranelift_codegen::settings;
use cranelift_codegen::settings::Configurable as _;
use cranelift_frontend::{FunctionBuilder, FunctionBuilderContext};
use cranelift_jit::{JITBuilder, JITModule};
use cranelift_module::{default_libcall_names, Linkage, Module};

// ---------------------------------------------------------------------------
// Rust reference kernels (compiled by LLVM at cargo-release opt-level 3)
// ---------------------------------------------------------------------------

fn fib_rust(n: i64) -> i64 {
    if n < 2 {
        n
    } else {
        fib_rust(n - 1) + fib_rust(n - 2)
    }
}

/// Exact same op order as the CLIF kernel: one pass per iteration,
/// in-place, low to high index. Bit-parity between backends is asserted.
fn axpy_rust(p: &mut [f64], a: f64, b: f64, iters: usize) {
    for _ in 0..iters {
        for x in p.iter_mut() {
            *x = *x * a + b;
        }
    }
}

// ---------------------------------------------------------------------------
// Cranelift codegen (pure SSA: block params, no Variable machinery)
// ---------------------------------------------------------------------------

/// fn fib(n: i64) -> i64 { if n < 2 { n } else { fib(n-1) + fib(n-2) } }
fn build_fib(module: &mut JITModule) -> cranelift_module::FuncId {
    let int = types::I64;

    let mut sig_ctx = module.make_context();
    sig_ctx.func.signature.params.push(AbiParam::new(int));
    sig_ctx.func.signature.returns.push(AbiParam::new(int));
    let fib_id = module
        .declare_function("fib", Linkage::Export, &sig_ctx.func.signature)
        .expect("declare fib");

    let mut ctx = module.make_context();
    ctx.func.signature.params.push(AbiParam::new(int));
    ctx.func.signature.returns.push(AbiParam::new(int));
    let mut fn_builder_ctx = FunctionBuilderContext::new();
    let mut fb = FunctionBuilder::new(&mut ctx.func, &mut fn_builder_ctx);

    let entry = fb.create_block();
    let base = fb.create_block();
    let rec = fb.create_block();
    fb.append_block_params_for_function_params(entry);
    fb.switch_to_block(entry);
    let n = fb.block_params(entry)[0];

    let two = fb.ins().iconst(int, 2);
    let lt = fb.ins().icmp(IntCC::SignedLessThan, n, two);
    fb.ins().brif(lt, base, &[], rec, &[]);

    fb.switch_to_block(base);
    fb.ins().return_(&[n]);

    fb.switch_to_block(rec);
    let fib_ref = module.declare_func_in_func(fib_id, fb.func);
    let one = fb.ins().iconst(int, 1);
    let n1 = fb.ins().isub(n, one);
    let c1 = fb.ins().call(fib_ref, &[n1]);
    let r1 = fb.inst_results(c1)[0];
    let n2 = fb.ins().isub(n, two);
    let c2 = fb.ins().call(fib_ref, &[n2]);
    let r2 = fb.inst_results(c2)[0];
    let sum = fb.ins().iadd(r1, r2);
    fb.ins().return_(&[sum]);

    fb.finalize(module.target_config());
    module.define_function(fib_id, &mut ctx).expect("define fib");
    fib_id
}

/// fn axpy_kernel(p: *mut f64, n: i64, a: f64, b: f64, iters: i64)
/// for it in 0..iters { for i in 0..n { p[i] = p[i]*a + b } }
/// Loop-carried values (i, it) travel as block params — plain SSA.
fn build_axpy(module: &mut JITModule) -> cranelift_module::FuncId {
    let int = types::I64;
    let flt = types::F64;

    let mut sig_ctx = module.make_context();
    for t in [int, int, flt, flt, int] {
        sig_ctx.func.signature.params.push(AbiParam::new(t));
    }
    let axpy_id = module
        .declare_function("axpy_kernel", Linkage::Export, &sig_ctx.func.signature)
        .expect("declare axpy");

    let mut ctx = module.make_context();
    for t in [int, int, flt, flt, int] {
        ctx.func.signature.params.push(AbiParam::new(t));
    }
    let mut fn_builder_ctx = FunctionBuilderContext::new();
    let mut fb = FunctionBuilder::new(&mut ctx.func, &mut fn_builder_ctx);

    let entry = fb.create_block();
    let outer_head = fb.create_block();
    let inner_init = fb.create_block();
    let inner_head = fb.create_block();
    let body = fb.create_block();
    let outer_inc = fb.create_block();
    let done = fb.create_block();

    // outer_head and inner_head each carry one i64 block param (it, i)
    fb.append_block_param(outer_head, int);
    fb.append_block_param(inner_head, int);

    fb.append_block_params_for_function_params(entry);
    fb.switch_to_block(entry);
    let (p, n, a, b, iters) = {
        let ps = fb.block_params(entry);
        (ps[0], ps[1], ps[2], ps[3], ps[4])
    };
    let zero = fb.ins().iconst(int, 0);
    fb.ins().jump(outer_head, &[BlockArg::from(zero)]);

    // outer_head: if it >= iters -> done else inner_init
    fb.switch_to_block(outer_head);
    let it = fb.block_params(outer_head)[0];
    let ge = fb.ins().icmp(IntCC::SignedGreaterThanOrEqual, it, iters);
    fb.ins().brif(ge, done, &[], inner_init, &[]);

    // inner_init: i = 0
    fb.switch_to_block(inner_init);
    let zero2 = fb.ins().iconst(int, 0);
    fb.ins().jump(inner_head, &[BlockArg::from(zero2)]);

    // inner_head: if i >= n -> outer_inc else body
    fb.switch_to_block(inner_head);
    let i = fb.block_params(inner_head)[0];
    let ge2 = fb.ins().icmp(IntCC::SignedGreaterThanOrEqual, i, n);
    fb.ins().brif(ge2, outer_inc, &[], body, &[]);

    // body: p[i] = p[i]*a + b
    fb.switch_to_block(body);
    let eight = fb.ins().iconst(int, 8);
    let byte_off = fb.ins().imul(i, eight);
    let addr = fb.ins().iadd(p, byte_off);
    let x = fb.ins().load(flt, MachMemFlags::trusted(), addr, 0);
    let mul = fb.ins().fmul(x, a);
    let y = fb.ins().fadd(mul, b);
    fb.ins().store(MachMemFlags::trusted(), y, addr, 0);
    let one = fb.ins().iconst(int, 1);
    let i1 = fb.ins().iadd(i, one);
    fb.ins().jump(inner_head, &[BlockArg::from(i1)]);

    // outer_inc: it = it + 1
    fb.switch_to_block(outer_inc);
    let one2 = fb.ins().iconst(int, 1);
    let it1 = fb.ins().iadd(it, one2);
    fb.ins().jump(outer_head, &[BlockArg::from(it1)]);

    // done
    fb.switch_to_block(done);
    fb.ins().return_(&[]);

    fb.finalize(module.target_config());
    module
        .define_function(axpy_id, &mut ctx)
        .expect("define axpy");
    axpy_id
}

// ---------------------------------------------------------------------------
// benchmark harness
// ---------------------------------------------------------------------------

fn time_ns<F: FnMut() -> T, T>(mut f: F, reps: usize) -> Vec<u128> {
    let mut out = Vec::with_capacity(reps);
    for _ in 0..3 {
        f(); // warmup
    }
    for _ in 0..reps {
        let t0 = Instant::now();
        let r = f();
        out.push(t0.elapsed().as_nanos());
        std::hint::black_box(r);
    }
    out.sort();
    out
}

fn median(v: &[u128]) -> u128 {
    v[v.len() / 2]
}

fn machine_note() -> String {
    let cpu = std::fs::read_to_string("/proc/cpuinfo")
        .ok()
        .and_then(|s| {
            s.lines()
                .find(|l| l.starts_with("model name"))
                .map(|l| l.split(':').nth(1).unwrap_or("").trim().to_string())
        })
        .unwrap_or_else(|| "unknown-cpu".to_string());
    cpu
}

fn main() {
    println!("# native-jit S2 prototype — Cranelift baseline JIT vs LLVM Rust");
    println!("# machine: {}", machine_note());
    println!("# cranelift opt_level=speed; LLVM: cargo release opt-level=3, lto=false");

    // ---- build the JIT ----
    let mut flag_builder = settings::builder();
    flag_builder.set("opt_level", "speed").expect("set opt_level");
    flag_builder.set("is_pic", "true").expect("set is_pic");
    let isa = cranelift_native::builder()
        .expect("host ISA")
        .finish(settings::Flags::new(flag_builder))
        .expect("finish ISA");
    let jit_builder = JITBuilder::with_isa(isa, default_libcall_names());
    let mut module = JITModule::new(jit_builder);

    let fib_id = build_fib(&mut module);
    let axpy_id = build_axpy(&mut module);
    module.finalize_definitions().expect("finalize");
    let fib_ptr = module.get_finalized_function(fib_id);
    let axpy_ptr = module.get_finalized_function(axpy_id);
    let fib_jit = unsafe { std::mem::transmute::<*const u8, extern "C" fn(i64) -> i64>(fib_ptr) };
    let axpy_jit = unsafe {
        std::mem::transmute::<*const u8, extern "C" fn(i64, i64, f64, f64, i64)>(axpy_ptr)
    };

    // ---- correctness first: cross-backend bit parity ----
    let got = fib_jit(25);
    assert_eq!(got, 75_025, "cranelift fib(25) wrong");
    assert_eq!(fib_rust(25), 75_025, "rust fib(25) wrong");

    const N: usize = 1_000;
    const ITERS: usize = 500;
    let a = 1.000_001_f64;
    let b = 0.25_f64;
    let mut buf_jit = vec![0.5_f64; N];
    let mut buf_rust = buf_jit.clone();
    let pj = buf_jit.as_mut_ptr() as i64;
    axpy_jit(pj, N as i64, a, b, ITERS as i64);
    axpy_rust(&mut buf_rust, a, b, ITERS);
    for i in 0..N {
        assert_eq!(
            buf_jit[i].to_bits(),
            buf_rust[i].to_bits(),
            "bit parity broken at {i}: jit {} rust {}",
            buf_jit[i],
            buf_rust[i]
        );
    }
    println!("# parity: fib(25)==75025 OK; axpy 500x1000 f64 updates bit-identical across Cranelift and LLVM");

    // ---- fib benchmark ----
    let reps = 15;
    // black_box keeps the literal argument opaque: without it LLVM folds
    // the whole fib recursion into a compile-time constant (observed:
    // "24 ns") and the comparison is meaningless.
    let jit_times = time_ns(|| fib_jit(std::hint::black_box(25)), reps);
    let rust_times = time_ns(|| fib_rust(std::hint::black_box(25)), reps);
    let jit_med = median(&jit_times);
    let rust_med = median(&rust_times);
    let ratio_fib = jit_med as f64 / rust_med as f64;
    println!("fib(25)  cranelift median = {:>9} ns", jit_med);
    println!("fib(25)  llvm-rust median = {:>9} ns", rust_med);
    println!(
        "fib(25)  ratio            = {:>9.3} x   (S2 gate: <= 2.0)",
        ratio_fib
    );

    // ---- axpy (n-body-morphic f64 loop) benchmark ----
    let mut buf = vec![0.5_f64; N];
    let p = buf.as_mut_ptr();
    let jit_t = time_ns(
        || {
            axpy_jit(p as i64, N as i64, a, b, ITERS as i64);
        },
        reps,
    );
    let mut stable = vec![0.5_f64; N];
    let rust_t = time_ns(
        || {
            axpy_rust(&mut stable, a, b, ITERS);
        },
        reps,
    );
    let jit_med = median(&jit_t);
    let rust_med = median(&rust_t);
    let ratio_axpy = jit_med as f64 / rust_med as f64;
    println!(
        "axpy      cranelift median = {:>9} ns  ({} x {} f64 updates)",
        jit_med, ITERS, N
    );
    println!("axpy      llvm-rust median = {:>9} ns", rust_med);
    println!(
        "axpy      ratio            = {:>9.3} x   (S2 gate: <= 2.0; LLVM may auto-vectorize this loop)",
        ratio_axpy
    );

    // keep the buffers alive so the optimizer cannot drop the work
    std::hint::black_box((&buf_jit, &buf_rust, &buf, &stable));

    // ---- verdict lines (prototype level; the official gate is V2-S2-B) ----
    println!(
        "GATE-S2-PROTOTYPE fib: {}  axpy: {}",
        if ratio_fib <= 2.0 { "PASS" } else { "FAIL" },
        if ratio_axpy <= 2.0 { "PASS" } else { "FAIL" }
    );
}
