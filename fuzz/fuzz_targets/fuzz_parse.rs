#![no_main]
// z-fuzz-libfuzzer (#49): in-process coverage-guided parser target; parse()
// is the exact entry the CLI uses, so a panic here is a real parser bug.
// Seeds: tests/ + examples/ via the corpus dir (cargo fuzz -merge once,
// then the nightly job explores).

use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    let src = std::str::from_utf8(data);
    if let Ok(src) = src {
        // depth caps + fuel live inside the parser; a panic escaping this
        // call is the finding (libFuzzer saves the input + the backtrace).
        let _ = operon::parser::parse(src);
    }
});
