# STRICT-CORE: the S1 subset spec (V2-S1-A)

**Status:** SPEC section for S1 (task V2-S1-A of
[docs/design/NEXT.md](NEXT.md)). This file defines the subset of Operon
that S1 implements end-to-end: grammar slice, typed AST slice, MIR
lowering surface, rejection rules, and the parity contract the S1
differential lane enforces. Where an older document (SPEC.md, README)
contradicts this file on the strict core, this file wins until S1 lands
(see NEXT.md §0 authority rule).

**Grounded in:** `src/mir.rs` (the S0 typed-MIR scaffold: `MirType`,
`Const`, `BinOp`, `UnOp`, `Instr`, `Terminator`, `Block`, `FnSig`,
`MirFn`, `Module`, `Interp`) and `src/parser.rs` (the Total Grammar
parser, where `fn` is currently a synonym of `gene`).

---

## 1. Why a subset

The existing language is dynamically shaped: `let` binds untyped, the
VM repairs malformed programs at runtime (Total Grammar 4-rung ladder),
and `fn` is one of nine spellings of `gene`. That is the compatibility
surface; it must not become the compilation target. The v2 architecture
(OWNER BRIEF §"Priority C") compiles a **strict core subset** to the
typed MIR, executes the MIR on the reference interpreter, and parity-
checks the result against the existing engines on the existing corpus.
Everything outside the subset keeps running exactly as today, on the
existing engines, under the existing rules. Nothing is removed before
its replacement and regression coverage exist (NEXT.md §5).

## 2. The grammar slice

The strict core accepts exactly these productions. Everything else is
rejected at parse time with a diagnostic (never repaired at runtime -
the Total Grammar repair ladder becomes `operon fix` / LSP quick-fixes
in the tooling lane, per NEXT.md §5 S1→S2).

### 2.1 Items (file level)

```
file        := item*
item        := fn_def
fn_def      := "fn" IDENT "(" params? ")" (":" type)? block
params      := param ("," param)*
param       := IDENT ":" type
```

- `fn` is the **only** function keyword in the strict core. In strict
  mode the parser no longer routes `fn` through the `gene` synonym
  table (`src/parser.rs` line 128); `gene`/`func`/`fun`/`def`/`funct`/
  `sub`/`lambda`/`proc` are rejected with a "use fn" diagnostic. The
  legacy corpus keeps parsing them on the legacy lane until S1 parity
  is frozen (NEXT.md §5 S1 row).
- A strict-core function is an **ordinary function**: direct calls
  only, no gene semantics attached (no regulation, no stress, no
  sequence streams). Genes remain a legacy-lane concept until their v2
  role is defined (networks, S3).

### 2.2 Statements

```
block       := "{" stmt* "}"
stmt        := let_stmt | assign_stmt | if_stmt | while_stmt
             | return_stmt | expr_stmt
let_stmt    := "let" IDENT ":" type "=" expr
assign_stmt := IDENT "=" expr
if_stmt     := "if" expr block ("else" (if_stmt | block))?
while_stmt  := "while" expr block
return_stmt := "return" expr?
expr_stmt   := expr
```

- `let` is **typed** and immutable: no re-assignment of a `let` name
  (a future `mut` marker, if the corpus parity work demands it, is a
  spec amendment: not a silent relaxation).
- `if` and `while` conditions must type as `Bool`. No truthiness
  coercion: `if x` where `x: Int` is a type error, not a runtime
  convention.
- `return` is optional in a `Unit` function; in a typed-return function
  every block path must return (exhaustiveness is checked in S1-B on
  the AST, matching the MIR type-checker's return-slot rule).

### 2.3 Expressions

```
expr        := comparison
comparison  := additive (("==" | "!=" | "<" | "<=" | ">" | ">=") additive)?
additive    := multiplicative (("+" | "-" | wrapping("+w","-w")) multiplicative)*
multiplicative := unary (("*" | "/" | "%" | wrapping("*w")) unary)*
unary       := ("-" | "!") unary | primary
primary     := INT | FLOAT | BOOL | STRING | IDENT | call_expr | "(" expr ")"
call_expr   := IDENT "(" args? ")"
```

- Arithmetic on `Int` is **checked** (overflow is a diagnostic, matching
  `BinOp::Add/Sub/Mul` in `src/mir.rs`); the explicit kernel opt-out is
  written `+w` / `-w` / `*w` and lowers to `AddWrap` / `SubWrap` /
  `MulWrap`. The wrapping choice lives in the source and the IR, so the
  interpreter, Cranelift and LLVM lower identical semantics.
- Comparisons and arithmetic are **homogeneous**: both operands must
  have the same type. The corpus idiom `10 == 10.0` (cross-type numeric
  equality) is a legacy-lane semantic and is rejected in the strict core
  with an "explicit conversion" diagnostic. An explicit numeric
  conversion function (`int_to_float`) arrives with S1-B's lowering if
  the corpus slice requires it: added as a named primitive, never as
  an implicit coercion.
- Strings are immutable values; the S1 slice has concatenation via the
  std primitive surface (`str_concat`) only if the corpus slice uses it
 : string *interpolation* stays legacy-lane until the typed AST grows
  it deliberately.
- Direct calls only (`Instr::Call`, callee = `FnId`): first-class
  functions, closures and function pointers are out of the subset (they
  arrive with explicit effect annotations, brief §8.5; they are not an
  S1 concern).

### 2.4 Types (S1 surface)

```
type := "Int" | "Float" | "Bool" | "Str" | "Unit"
      | "[" type "]"                    // list, S1-Core-1
      | type "?"                        // option, S1-Core-1
      | "Result" "<" type ">"           // result, S1-Core-1
```

- Layer **S1-Core-0** (the first S1 parity lane) is the scalar slice:
  `Int | Float | Bool | Str | Unit`: exactly today's `MirType`, zero
  MIR growth, lowering is mechanical.
- Layer **S1-Core-1** grows `MirType` with `List(elem)` / `Option(inner)`
  / `Result(ok, err)` (the growth `src/mir.rs` §types comment anticipates:
  "Grows with the strict core subset (V2-S1-A: lists, options, results);
  grows ONLY with a type"). Each new type lands together with its
  instructions (`ListNew/ListLen/ListGet/ListSet`, `OptNew/OptUnwrap`
  family, `ResNew/ResUnwrap` family) and its interpreter rules, before
  any backend consumes it.
- Negative indexing, heterogeneous lists and `Any` escape hatches are
  **out** of the strict core (brief §"Types": promote types into a
  trusted strict mode; `Any` stays an escape hatch of the legacy lane).
- Ownership/views note: scalars are value semantics, so the scalar
  layer cannot exercise the ownership model. `List` in S1-Core-1 is
  **move-by-default** (a `Copy` marker does not exist in the core;
  explicit `copy(expr)` arrives with the views work, S2). Scoped views
  (`from(param)`, returned iterators, view rules) enter the strict core
  only after the S0 view-exercise evidence
  ([VIEW-EXERCISE.md](VIEW-EXERCISE.md)) is re-validated on the lowered
  path: they are spec-gated, not spec-promised.

### 2.5 Out of the subset (explicit non-goals for S1)

genes and their regulation ladder · phenotypes · stress/rescue ·
sequences and streams · channels/select · cells/networks · effects and
suspension (`Terminator` grows a suspension family in S4) · placement
annotations · string interpolation · dynamic dispatch · runtime Total
Grammar repair · synonyms of `fn` · truthiness coercion · cross-type
numeric equality · `Any`.

Each item above is a *deferred v2 feature with a planned home* (NEXT.md
§6, S3–S5) or a *legacy-lane behavior that the strict core deliberately
refuses*: the difference is recorded here so "not yet" cannot drift
into "accidentally forever".

## 3. The typed AST slice

The strict parser produces a typed AST: every binding carries its
`MirType` (or a type error), every expression is annotated bottom-up,
and no node exists that cannot lower to a `src/mir.rs` instruction
family:

| AST node | lowers to |
|---|---|
| `FnDef{name, params, ret, body}` | `MirFn{name, sig: FnSig, slot_tys, blocks}` |
| `Let{name, ty, init}` | slot alloc + `LoadConst`/expression lowering |
| `Assign{name, expr}` | `Copy` (slot-to-slot, values owned) |
| `Bin{op, lhs, rhs}` | `Bin{op}` (checked/wrapping per §2.3) |
| `Un{op, v}` | `Un{op}` |
| `Call{callee, args}` | `Instr::Call{callee: FnId}` |
| `If{cond, then, else}` | `Br{cond, then, otherwise}` + blocks |
| `While{cond, body}` | `Jmp`/`Br` back-edge blocks |
| `Return{expr?}` | `Terminator::Ret` |
| literal | `LoadConst{val: Const}` |

Slot discipline: one frame slot per binding (`slot_tys` indexed by
slot id, params first: the S0 `MirFn` layout). The AST→slot assignment
is deterministic (declaration order), so the same program lowers
byte-identically on every run: a precondition for the differential
lane's "same input, same MIR" check.

## 4. Rejection rules (diagnostics, never repair)

The strict parser/type-checker rejects with a diagnostic that names the
production and the fix. The full list S1-B must implement, each with a
golden diagnostic test:

1. unknown identifier / duplicate binding in a block
2. type mismatch in `let`, assignment, argument, condition, return
3. cross-type comparison or arithmetic (§2.3)
4. re-assignment of a `let` name
5. non-`Bool` condition
6. call to an unknown function or with wrong arity/argument types
7. non-exhaustive returns in a typed-return function
8. legacy keyword in strict mode (`gene`, `func`, `def`, ...) →
   "strict core uses fn"
9. subset-external construct (phenotype, stress, sequence, channel,
   cell, network, effect, suspension point) → "outside the strict core
   (see docs/design/STRICT-CORE.md §2.5)"

These are compile-time diagnostics in the strict lane. The Total
Grammar repair machinery stays untouched on the legacy lane and gains
its `operon fix` / LSP surface in the S1→S2 migration (NEXT.md §5) -
the repair code is *tooling* from S1 onward, never silent runtime
semantics of the compiled path.

## 5. Parity contract (the S1 gate)

A program is **in the S1 corpus slice** iff (a) it parses under the
strict grammar, (b) type-checks under §2's rules, and (c) exercises
only the instruction families its layer declares. For every such
program, on every commit:

- the **MIR interpreter** (`src/mir.rs` `Interp`) must produce output
  identical to the **existing engines** (tree-walk interpreter / VM
  OIR1) on the same input, byte-for-byte, including note formatting for
  the diagnostics the subset can emit (checked-arithmetic overflow);
- the differential harness gains the MIR lane as a third engine on this
  slice (V2-S1-B), reporting per file: `N/N MATCH, 0 diverge` (NEXT.md
  §7 evidence policy);
- a legacy corpus file that fails the subset membership test (§5 a–c)
  is **skipped by the S1 lane, recorded with its rejection reason**, and
  does not count as a parity failure. The per-file pass/skip/fail table
  lives in [S1-CORPUS-BASELINE.md](S1-CORPUS-BASELINE.md) (oracle-lane
  baseline: every file in `tests/differential/` runs on the Python
  oracle today, so engine-vs-oracle divergence is attributable before
  the MIR lane joins).

Kill-criterion link (NEXT.md §8.3): persistent parity gaps after
narrowing the subset trigger a MIR redesign discussion, not a silent
subset reduction.

## 6. Acceptance criteria for V2-S1-A

1. This section exists, reviewed against `src/mir.rs` (types/instrs
   named here exist there, or their growth is declared in §2.4).
2. The `fn`-keyword split, the wrapping-operator spelling (`+w`), and
   the homogeneous-comparison rule are each traceable to a brief or
   corpus fact cited in this file.
3. S1-B can be implemented from §2–§4 without further design decisions:
   every grammar production, AST node, rejection rule and layer
   boundary is normative here.
