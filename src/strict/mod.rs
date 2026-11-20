//! mod.rs — the S1 strict core facade: compile (index, check, lower,
//! validate), run through the reference interpreter, and the
//! `operon strict-run` CLI command.

mod ast;
mod check;
mod lex;
mod lower;
#[cfg(test)]
mod tests;
mod parse;
mod parse_expr;

use ast::FnDef;
use check::Checker;
use lex::lex;
use lower::Lowerer;
use parse::Parser;

use crate::mir::{FnId, FnSig, MirError, MirType, Module};
use std::collections::HashMap;
use std::fmt;

#[derive(Clone, Debug)]
pub struct StrictError {
    pub line: usize,
    pub msg: String,
}

impl StrictError {
    pub fn new(line: usize, msg: impl Into<String>) -> StrictError {
        StrictError { line, msg: msg.into() }
    }
}

impl fmt::Display for StrictError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "line {}: {}", self.line, self.msg)
    }
}

/// Builds the fn-name index (order + signature) with module-level checks:
/// unique names, exactly one `main`, `main` is `() -> Unit`.
fn build_index(fns: &[FnDef]) -> Result<HashMap<String, (usize, FnSig)>, StrictError> {
    let mut index = HashMap::new();
    for (i, f) in fns.iter().enumerate() {
        let sig = FnSig {
            params: f.params.iter().map(|(_, t)| *t).collect(),
            ret: f.ret,
        };
        if index.insert(f.name.clone(), (i, sig.clone())).is_some() {
            let msg = format!("duplicate function name '{}' (STRICT-CORE §4 rule 1)", f.name);
            return Err(StrictError::new(f.line, msg));
        }
    }
    match index.get("main") {
        None => Err(StrictError::new(1, "no `main` — the strict core entry point is `fn main()`")),
        Some((main_i, sig)) => {
            if !sig.params.is_empty() || sig.ret != MirType::Unit {
                let msg = "`main` must be `fn main()` — no parameters, Unit return (STRICT-CORE §2.1)";
                return Err(StrictError::new(fns[*main_i].line, msg));
            }
            Ok(index)
        }
    }
}

/// Type-checks one fn body (rule 7 lives here: non-Unit fns must return on
/// every path).
fn check_fn(f: &FnDef, index: &HashMap<String, (usize, FnSig)>) -> Result<(), StrictError> {
    let (_, sig) = &index[&f.name];
    let mut ck = Checker {
        fns: index,
        scopes: Vec::new(),
        ret: sig.ret,
    };
    ck.scopes.push(HashMap::new());
    for (pname, pty) in &f.params {
        ck.scopes[0].insert(pname.clone(), *pty);
    }
    // the body gets its OWN scope: lets live at depth >= 1 so rule 4 (a let
    // is not a param) and rule 1 (per-block duplicates) see the right depth
    let terminated = ck.check_block(&f.body)?;
    if sig.ret != MirType::Unit && !terminated {
        let msg = format!(
            "not every path of `fn {}` returns a {:?} — non-Unit functions must return on every path (STRICT-CORE §4 rule 7)",
            f.name, sig.ret
        );
        return Err(StrictError::new(f.line, msg));
    }
    Ok(())
}

/// Compiles strict-core source to a validated typed-MIR module plus the
/// `main` entry id (STRICT-CORE §2.1: a strict program is a `fn main()`).
pub fn compile(src: &str) -> Result<(Module, FnId), StrictError> {
    let toks = lex(src)?;
    let mut p = Parser { toks, pos: 0 };
    let fns = p.parse_file()?;
    if fns.is_empty() {
        return Err(StrictError::new(1, "no functions — the strict core needs `fn main()`"));
    }
    let index = build_index(&fns)?;
    for f in &fns {
        check_fn(f, &index)?;
    }
    let sigs: HashMap<String, FnSig> =
        index.iter().map(|(k, (_, s))| (k.clone(), s.clone())).collect();
    let fns_index: HashMap<String, usize> =
        index.iter().map(|(k, (i, _))| (k.clone(), *i)).collect();
    let mut lowered = Vec::new();
    for f in &fns {
        lowered.push(Lowerer::lower_fn(f, &fns_index, &sigs)?);
    }
    let module = Module { fns: lowered };
    module
        .validate()
        .map_err(|e| StrictError::new(1, format!("lowering produced an invalid module: {e}")))?;
    let entry = module.fn_by_name("main").expect("main presence checked in build_index");
    Ok((module, entry))
}

/// Runs a compiled module's `main` with the portable fuel budget and returns
/// the printed lines (the differential lane compares these byte-for-byte)
/// plus the charged ops (the portable cost unit).
pub fn run_module(module: &Module, entry: FnId, fuel: u64) -> Result<(Vec<String>, u64), MirError> {
    let mut it = crate::mir::Interp::with_fuel(fuel);
    it.run(module, entry, Vec::new())?;
    Ok((std::mem::take(&mut it.out), it.charged()))
}

struct StrictArgs {
    fuel: u64,
    dump_mir: bool,
    file: Option<String>,
}

fn parse_args(args: &[String]) -> Result<StrictArgs, String> {
    let mut out = StrictArgs { fuel: 1_000_000_000, dump_mir: false, file: None };
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--fuel" => {
                i += 1;
                out.fuel = args.get(i).and_then(|s| s.parse::<u64>().ok()).ok_or("--fuel needs a number")?;
            }
            "--dump-mir" => out.dump_mir = true,
            other if out.file.is_none() => out.file = Some(other.to_string()),
            other => return Err(format!("unexpected argument '{other}'")),
        }
        i += 1;
    }
    if out.file.is_none() {
        return Err("missing <file.op>".to_string());
    }
    Ok(out)
}

/// `operon strict-run <file.op> [--fuel N] [--dump-mir]`: compile the
/// strict core, run the MIR reference interpreter, print the promote lines.
/// stdout is program output only; diagnostics go to stderr so the lane can
/// classify SKIP (2) / runtime error (1) / tooling panic (101).
pub fn strict_run_command(args: &[String]) {
    let parsed = match parse_args(args) {
        Ok(a) => a,
        Err(e) => {
            eprintln!("strict: {e}");
            eprintln!("usage: operon strict-run <file.op> [--fuel N] [--dump-mir]");
            std::process::exit(2);
        }
    };
    let path = parsed.file.expect("parse_args requires a file");
    let src = match std::fs::read_to_string(&path) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("strict: cannot read {path}: {e}");
            std::process::exit(2);
        }
    };
    let (module, entry) = match compile(&src) {
        Ok(m) => m,
        Err(e) => {
            eprintln!("strict: {path}:{e}");
            std::process::exit(2);
        }
    };
    if parsed.dump_mir {
        println!("{module:#?}");
    }
    match run_module(&module, entry, parsed.fuel) {
        Ok((lines, _charged)) => {
            for l in lines {
                println!("{l}");
            }
        }
        Err(e) => {
            eprintln!("strict: runtime error in {path}: {e}");
            std::process::exit(1);
        }
    }
    // belt-and-braces: nothing falls through to the generic flag parser
    // with a strict-run argv
    std::process::exit(0);
}
