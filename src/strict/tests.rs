//! Tests: golden rejections (one per STRICT-CORE §4 rule), deterministic
//! lowering, checked/wrapping arithmetic, fuel, and display-format parity
//! with the legacy engine's promote builtin (the S1 differential contract
//! in miniature).

#![cfg(test)]

use super::{compile, run_module, StrictError};
use crate::mir::{BinOp, Interp, MirError};
use crate::value::Value as Legacy;

fn compile_ok(src: &str) -> (crate::mir::Module, crate::mir::FnId) {
    compile(src).unwrap_or_else(|e| panic!("expected OK, got: {e}"))
}

fn run_ok(src: &str) -> Vec<String> {
    let (m, entry) = compile_ok(src);
    match run_module(&m, entry, 1_000_000_000) {
        Ok((lines, _)) => lines,
        Err(e) => panic!("runtime failed: {e}"),
    }
}

fn err_of(src: &str) -> String {
    match compile(src) {
        Ok(_) => panic!("expected a strict-core rejection, got OK for:\n{src}"),
        Err(e) => e.msg,
    }
}

#[test]
fn recursive_fib_and_iterative_sum() {
    let src = r#"
fn fib(n: Int) -> Int {
  if n < 2 { return n }
  return fib(n - 1) + fib(n - 2)
}
fn sum_to(n: Int) -> Int {
  if n <= 0 { return 0 }
  return n + sum_to(n - 1)
}
fn main() {
  promote(fib(10))
  promote(sum_to(100))
}
"#;
    assert_eq!(run_ok(src), ["55", "5050"]);
}

#[test]
fn while_loop_over_assignable_params() {
    // reading 1: `let` is immutable (§2.2 rule 4); the grammar's assign_stmt
    // targets parameters — this is what makes `while` expressible
    let src = r#"
fn count_down(n: Int) -> Int {
  while n > 0 {
    n = n - 1
  }
  return n
}
fn main() {
  promote(count_down(9))
}
"#;
    assert_eq!(run_ok(src), ["0"]);
}

#[test]
fn if_else_join_and_early_return() {
    let src = r#"
fn classify(x: Int) -> Str {
  if x < 0 {
    return "neg"
  } else {
    if x == 0 {
      return "zero"
    } else {
      return "pos"
    }
  }
}
fn main() {
  promote(classify(-5), classify(0), classify(7))
}
"#;
    assert_eq!(run_ok(src), ["neg zero pos"]);
}

#[test]
fn wrapping_operators_wrap_checked_operators_trap() {
    let wrap = "fn main() { let m: Int = 9223372036854775807 +w 1 promote(m) }";
    assert_eq!(run_ok(wrap), ["-9223372036854775808"]);

    let checked = "fn main() { let m: Int = 9223372036854775807 + 1 promote(m) }";
    let (m, entry) = compile_ok(checked);
    match run_module(&m, entry, 1_000_000_000) {
        Err(MirError::Overflow { op: BinOp::Add }) => {}
        other => panic!("expected checked overflow, got {other:?}"),
    }
}

#[test]
fn display_parity_with_legacy_promote() {
    // THE differential contract in miniature: for scalar values, the MIR
    // Print rendering must equal the legacy engine's promote rendering,
    // byte-for-byte. Floats share crate::value::format_float.
    let src = r#"
fn main() {
  promote(2.5)
  promote(0.1)
  promote(1e20)
  promote(123456789.0)
  promote(true)
  promote(false)
  promote("raw str with \"escape\"")
  promote(-42)
}
"#;
    let got = run_ok(src);
    let want = [
        Legacy::Float(2.5).display(),
        Legacy::Float(0.1).display(),
        Legacy::Float(1e20).display(),
        Legacy::Float(123456789.0).display(),
        Legacy::Bool(true).display(),
        Legacy::Bool(false).display(),
        Legacy::Str("raw str with \"escape\"".into()).display(),
        Legacy::Int(-42).display(),
    ];
    for (i, (g, w)) in got.iter().zip(want.iter()).enumerate() {
        assert_eq!(g, w, "line {i} display parity");
    }
}

#[test]
fn lowering_is_deterministic() {
    let src = r#"
fn fib(n: Int) -> Int {
  if n < 2 { return n }
  return fib(n - 1) + fib(n - 2)
}
fn main() {
  let a: Int = fib(6)
  promote(a)
}
"#;
    let (m1, _) = compile_ok(src);
    let (m2, _) = compile_ok(src);
    assert_eq!(format!("{m1:?}"), format!("{m2:?}"), "same input, same MIR");
}

#[test]
fn fuel_is_charged_and_exhaustible() {
    let (m, entry) = compile_ok("fn main() { promote(1) promote(2) }");
    let mut it = Interp::with_fuel(1);
    match it.run(&m, entry, Vec::new()) {
        Err(MirError::OutOfFuel { .. }) => {}
        other => panic!("expected fuel exhaustion, got {other:?}"),
    }
    // 2 promotes charge 2 ops — far under the 1e9 budget, so this cannot fail
    let (_, charged) = run_module(&m, entry, 1_000_000_000).expect("fuel far above the charge");
    assert!(charged > 0, "promote charges fuel");
}

// ---- rejection goldens (one per STRICT-CORE §4 rule) ----

#[test]
fn rule1_unknown_identifier_duplicate_binding() {
    assert!(err_of("fn main() { let a: Int = b }").contains("unknown identifier 'b'"));
    assert!(err_of("fn main() { let a: Int = 1 let a: Int = 2 }").contains("duplicate binding 'a'"));
    assert!(err_of("fn f() {} fn f() {} fn main() { }").contains("duplicate function name 'f'"));
}

#[test]
fn rule2_type_mismatch_positions() {
    assert!(err_of("fn main() { let a: Int = 2.5 }").contains("declared Int"));
    assert!(err_of("fn f() -> Int { return true } fn main() { }").contains("return value is Bool"));
    assert!(err_of("fn f(x: Int) {} fn main() { f(\"s\") }").contains("argument 1 is Str"));
}

#[test]
fn rule3_cross_type_rejected() {
    // the corpus idiom 10 == 10.0 is legacy-lane only
    assert!(err_of("fn main() { let e: Bool = 10 == 10.0 }").contains("cross-type"));
    assert!(err_of("fn main() { let s: Str = 1 + \"a\" }").contains("cross-type"));
    assert!(err_of("fn main() { let b: Bool = true < false }").contains("invalid on Bool"));
}

#[test]
fn rule4_let_is_immutable_params_are_assignable() {
    let msg = err_of("fn main() { let a: Int = 1 a = 2 }");
    assert!(msg.contains("the strict core `let` is immutable"), "{msg}");
    // params ARE the assignable surface (reading 1 in the module docs)
    let ok = "fn f(n: Int) -> Int { n = n + 1 return n } fn main() { promote(f(1)) }";
    assert_eq!(run_ok(ok), ["2"]);
}

#[test]
fn rule5_no_truthiness_coercion() {
    assert!(err_of("fn main() { if 1 { } }").contains("not Bool"));
    assert!(err_of("fn main() { while \"x\" { } }").contains("not Bool"));
}

#[test]
fn rule6_calls() {
    assert!(err_of("fn main() { f() }").contains("unknown function 'f'"));
    assert!(err_of("fn f(x: Int) {} fn main() { f(1, 2) }").contains("wants 1 argument(s)"));
    // recursion IS a known function at check time
    let ok = "fn f(n: Int) -> Int { if n <= 0 { return 0 } return f(n - 1) } fn main() { promote(f(3)) }";
    assert_eq!(run_ok(ok), ["0"]);
}

#[test]
fn rule7_non_unit_fns_must_return_on_every_path() {
    assert!(err_of("fn f(x: Int) -> Int { if x > 0 { return 1 } } fn main() { }").contains("not every path"));
    // Unit functions may fall off the end
    assert!(compile_ok("fn main() { }").0.fn_by_name("main").is_some());
}

#[test]
fn rule8_legacy_fn_synonyms_pointed_rejection() {
    for kw in ["gene", "func", "def", "lambda"] {
        let src = format!("{kw} f() {{ }} fn main() {{ }}");
        let e = err_of(&src);
        assert!(e.contains("strict core uses fn"), "keyword {kw}: {e}");
    }
}

#[test]
fn rule9_subset_external_constructs_pointed_rejection() {
    let e = err_of("phenotype p {} fn main() { }");
    assert!(e.contains("outside the strict core"), "{e}");
    let e = err_of("fn main() { for x in y { } }");
    assert!(e.contains("outside the strict core"), "{e}");
    // top-level statements: file level is fn-only
    let e = err_of("promote(1)");
    assert!(e.contains("file level is `fn` definitions only"), "{e}");
}

#[test]
fn promote_is_statement_only() {
    assert!(err_of("fn main() { let u: Unit = promote(1) }").contains("statement effect"));
    assert!(err_of("fn main() { promote() }").contains("at least one printable argument"));
    // Unit values are not printable
    assert!(err_of("fn f() {} fn main() { promote(f()) }").contains("Unit is not printable"));
}

#[test]
fn unreachable_statements_rejected() {
    let msg = err_of("fn f() -> Int { return 1 return 2 } fn main() { }");
    assert!(msg.contains("unreachable statement"), "{msg}");
    let msg = err_of("fn f(x: Int) -> Int { if x > 0 { return 1 } else { return 2 } return 3 } fn main() { }");
    assert!(msg.contains("unreachable statement"), "{msg}");
}

#[test]
fn string_and_comparison_surface() {
    // ternaries are NOT in the grammar — must reject, not parse
    let ternary = "fn main() { let s: Str = \"a\" + \"b\" == \"ab\" ? \"y\" : \"n\" }";
    assert!(err_of(ternary).contains("expected"));
    let ok = r#"
fn main() {
  promote("a" < "b")
  promote("b" == "b")
  promote("a" != "b")
}
"#;
    assert_eq!(run_ok(ok), ["true", "true", "true"]);
}

#[test]
fn precedence_pins() {
    let src = r#"
fn main() {
  promote(2 + 3 * 4)
  promote((2 + 3) * 4)
  promote(10 - 3 - 4)
  promote(2 * 3 * 4)
  promote(-2 * 3)
  promote(-(2 + 3))
  promote(!true)
  promote(!(1 == 2))
}
"#;
    assert_eq!(run_ok(src), ["14", "20", "3", "24", "-6", "-5", "false", "true"]);
}

#[test]
fn strict_error_display_carries_line() {
    let e = compile("fn main() { let a: Int = b }").unwrap_err();
    assert_eq!(e.line, 1);
    assert!(StrictError::new(3, "x").to_string().contains("line 3"));
}
