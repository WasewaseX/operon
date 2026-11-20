#![no_main]
// z-fuzz-libfuzzer (#49): in-process evaluator target, fuel-capped: a
// panic/abort escaping exec_block IS the finding; invalid UTF-8 bytes are
// skipped (the file layer already rejects them, see #113's read contract).

// LEAK POLICY (measured, deliberate): run with -detect_leaks=0. The value
// graph is process-lifetime by design, so LeakSanitizer flags the runtime's
// own teardown model, not a finding; leaks stay out of scope here.

use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    if let Ok(src) = std::str::from_utf8(data) {
        let prog = operon::parser::parse(src);
        let mut interp = operon::interp::Interp::new();
        // Fuel cap: the documented 20M-step run bound (25s wall on the CI
        // runners); Interp::new() defaults to 200M (REPL pool), which would
        // burn ~2.5 minutes per adversarial input instead of ~15s.
        interp.step_budget = 20_000_000;
        let genv = interp.global.clone();
        // exec_block returns Err(Stress) on containment — an expected
        // outcome, never a finding. A panic escaping this call IS one.
        let _ = interp.exec_block(&genv, &prog.stmts);
    }
});
