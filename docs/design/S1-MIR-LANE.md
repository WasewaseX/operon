# S1 MIR LANE: the strict core runs on the typed MIR (V2-S1-B)

**Status:** DONE (2026-11-21). Task V2-S1-B of [docs/design/NEXT.md](NEXT.md):
*"lower strict-core AST slice → typed MIR; wire the MIR interpreter into the
differential harness as a third lane on a corpus subset."*

**Evidence policy compliance (NEXT.md §7):** every claim below carries the
exact command and output. Machine note: Linux x86_64 sandbox, Rust 1.100.0
stable, built `--release`, cargo clean build 36.87s.

---

## 1. What landed

| piece | file | notes |
|---|---|---|
| strict lexer/parser/type-checker/lowerer | `src/strict/` (mod, ast, lex, parse, parse_expr, check, lower, tests; each file under the 400-line budget, each fn under the 80-line/complexity-15 budgets) | the S1-Core-0 scalar slice (`Int \| Float \| Bool \| Str \| Unit`), spec: [STRICT-CORE.md](STRICT-CORE.md) §2–§4 |
| `Instr::Print` + `Interp::out` sink + `FnBuilder::print` / `new_block_unterminated` / `patch_term` (pending-terminator ledger) | `src/mir.rs` | the subset's one effect; display parity via `crate::value::format_float` (no duplicated formatter) |
| CLI: `operon strict-run <file.op> [--fuel N] [--dump-mir]` | `src/main.rs` (+ `pub mod strict;` in `src/lib.rs`) | stdout carries ONLY program output; diagnostics on stderr, exit 2 |
| differential harness `--lane mir` | `bootstrap/harness.py` | per-file SKIP-with-reason / MATCH / DIVERGE rows, exit contract preserved for the other lanes |
| S1 corpus slice seeds | `tests/differential/strict/*.op` (10 files) | written in the intersection language: valid strict-core AND valid legacy source |

## 2. Gate results

### 2.1 Unit tests

```
$ cargo test --release --lib
test result: ok. 166 passed; 0 failed; 0 ignored; 0 measured
```

The strict suite adds: recursive fib / iterative sum, while-over-params,
if/else join + early return, checked-vs-wrapping arithmetic (i64::MAX + 1
traps, `+w` wraps to i64::MIN), display-format parity against the legacy
engine's `Value::display` (floats share one formatter), deterministic
lowering (same input → same MIR Debug string), fuel charge + exhaustion, and
one golden rejection per STRICT-CORE §4 rule (1 unknown/duplicate, 2 type
mismatch, 3 cross-type, 4 let-immutability, 5 no truthiness, 6 call shape,
7 exhaustiveness, 8 legacy fn synonyms, 9 subset-external constructs).

### 2.2 The differential lane

```
$ python3 bootstrap/harness.py --bin target/release/operon --lane mir
mir lane (strict core -> typed MIR -> reference interpreter vs the VM engine)
  MATCH    tests/differential/strict/strict_arith_int.op
  MATCH    tests/differential/strict/strict_bool.op
  MATCH    tests/differential/strict/strict_calls.op
  MATCH    tests/differential/strict/strict_fib.op
  MATCH    tests/differential/strict/strict_float.op
  MATCH    tests/differential/strict/strict_if_chain.op
  MATCH    tests/differential/strict/strict_mixed.op
  MATCH    tests/differential/strict/strict_str.op
  MATCH    tests/differential/strict/strict_sum_rec.op
  MATCH    tests/differential/strict/strict_while_params.op
  SKIP     tests/differential/<116 legacy files> (reason per file)
mir lane result: 10 MATCH, 0 diverge, 116 skipped (not in the S1 subset)
```

**10/10 MATCH, 0 diverge** on the S1 slice. Each MATCH row = `operon
strict-run` output byte-identical to `operon run` (VM engine) on stdout AND
exit code.

Skip-reason distribution over the 116 legacy files (STRICT-CORE §5:
skipped-with-reason, never a silent drop):

| reason | count |
|---|---|
| subset-external syntax (`[`, `.`, `;`, `?`, `@`, `~`) | 103 |
| top-level statements (file level is `fn` only) | 9 |
| legacy function keyword (`gene` …) → "strict core uses fn" | 7 |
| other parse shape (e.g. item at stmt position) | 2 |

### 2.3 Existing lanes untouched

`--lane both` (VM-vs-oracle + tree-walk-vs-oracle) code paths are unchanged;
the mir lane is opt-in via `--lane mir` and exits under its own counters.

## 3. Spec readings recorded here (none silent)

1. **Assignment surface (STRICT-CORE §2.2 + §4 rule 4).** `let` is immutable;
   the grammar's `assign_stmt` targets function PARAMETERS: the §3 table's
   `Assign → Copy` row made real. This is what makes `while` expressible in
   the scalar layer (`n = n - 1` on a parameter). Assigning a `let` name is
   rejected with the rule-4 diagnostic. A future `mut` marker remains a spec
   amendment, exactly as the spec says.
2. **Print surface.** The subset's builtin is `promote(...)`: the corpus
   print builtin: lowering to `Instr::Print{args}` (1+ printable scalar
   args, Unit return, statement-only: `promote` inside an expression is a
   compile error). The `Print` line is rendered by the SAME format rules as
   the legacy engine's promote (`Value::display`; floats via
   `crate::value::format_float`), which is what makes byte-identical lanes
   possible.
3. **Return annotation spelling.** The spec grammar says `":" type` after
   params; the parser accepts BOTH `: T` (spec-canonical) and `-> T`
   (corpus-compatible). Intersection slice files use `->` because the legacy
   parser honors `->` and silently ignores `:`.
4. **Int `/` and `%` are OUT of the S1-B slice.** Legacy Int division is
   Python-style (`7 / -2` → `-3.5`, `%` floors: `-7 % 3` → `2`: probed on
   commit-tree v2.11.1); the v2 MIR uses checked 64-bit truncated division
   (`mir.rs` `BinOp::Div/Rem`). This is a real, deliberate semantics
   divergence between the eras, owned by the brief ("Int is checked 64-bit
   everywhere"), not a bug to paper over with a parity workaround. Corpus
   files using Int `/`/`%` skip the lane with their reason; Float `/`/`%`
   semantics are identical and ARE in the slice (`strict_float.op`).
   Revisit when S1-C defines the strict-core numeric-kernel pins.
5. **Logic operators.** `&&`/`||` are `BinOp::And/Or` in the MIR but NOT in
   the STRICT-CORE §2.3 grammar: so the strict core has no logic-operator
   syntax yet; conjunction is spelled with nested ifs in slice files. They
   arrive by spec amendment, not by the lowering growing them silently.

## 4. What this does NOT claim

- No S2 claims: the 2× gate stays blocked on V2-S2-C (fib 2.62× prototype
  evidence unchanged).
- No claim that the 116 skipped files are semantically covered by the MIR
  lane: they are legacy-lane programs; the lane records WHY each is outside
  the subset (the table above), which is exactly the §5 contract.
- Runtime-error output parity (checked-overflow notes, divide-by-zero) is
  not in this slice; slice files avoid overflow/div-zero inputs, and the
  lane treats strict-runtime-error + legacy-reject as SKIP (both-reject),
  never as a silent match.

## 5. Next

- V2-S1-C (IN PROGRESS): grow the slice toward the S1-Core-1 types
  (List/Option/Result land with their instructions before any backend
  consumes them), and re-run the oracle lane + mir lane on the grown corpus.
- V2-S2-C (READY, unblocks S2): backend investigation on real hardware with
  the Cranelift prototype; this sandbox run records the parity gate, not the
  native-speed gate.
