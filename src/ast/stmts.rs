//! ast/stmts.rs, the statement layer: MatchPat, destructuring Pat,
//! Stmt, Program and the W08r line-extraction helpers.

use std::sync::Arc;

use super::{BinOp, Expr, Note};
use super::decls::*;

#[derive(Debug, Clone)]
pub enum MatchPat {
    Lit(Expr),        // literal-only pattern
    Multi(Vec<Expr>), // comma-separated literals
    Bind(String),     // identifier binds value
    Wild,             // _
    /// W02 (match-v2): variant constructor pattern, `Some(p)`, `None`,
    /// `Ok(p)`, `Err(p)`. The payload is itself a pattern (nestable);
    /// `None` payload = tag-only form (matches the tag with any payload).
    /// Unknown capitalized tags fall back to Bind with a note (Total
    /// Grammar: never a rejection).
    Variant(String, Option<Box<MatchPat>>),
    /// W02: list pattern, `[a, b, *rest]`. Element patterns nest; `*rest`
    /// binds the remaining tail as a List. Without `*rest` the length must
    /// match exactly.
    ListPat {
        elems: Vec<MatchPat>,
        rest: Option<String>,
    },
    /// W02: map pattern, `{x, y: p}`. Each key must be present; an
    /// optional sub-pattern is matched against the value.
    MapPat {
        keys: Vec<(String, Option<Box<MatchPat>>)>,
    },
    /// W02: or-pattern, `p1 | p2 | ...`; alternatives tried in order,
    /// first match binds.
    Or(Vec<MatchPat>),
    /// W02: guarded arm, `pat if cond`; the condition sees the pattern's
    /// bindings. Guard false (or contained) = arm misses, matching moves on.
    Guard(Box<MatchPat>, Expr),
}

/// L1a: destructuring patterns (let / for). `Bind` binds the whole item;
/// `List` destructures a List (elements are patterns; `*rest` captures the
/// tail); `Map` destructures a Map (each name reads that key). Soft-miss
/// semantics: wrong container type or missing element/key binds Null with a
/// note, Total Grammar: a pattern never hard-fails a run.
#[derive(Debug, Clone)]
pub enum Pat {
    Bind(String),
    List {
        elems: Vec<Pat>,
        rest: Option<String>, // *rest, tail after the fixed elements
    },
    Map {
        keys: Vec<String>,
    },
}

#[derive(Debug, Clone)]
pub enum Stmt {
    Let(String, Expr),
    /// W05: `const NAME = expr`, an immutable binding. The bound value is
    /// deep-frozen (lists/maps inside it can never be mutated, mutation
    /// raises a catchable `frozen` Stress), and the NAME can never be
    /// reassigned (rebinding defines anew; assignment is the `frozen` stress).
    LetConst(String, Expr),
    /// W01 (L2c): annotated definition, `let n: int = 3`. The annotation is
    /// checked when the statement binds (mismatch = catchable `unfolded`
    /// Stress, SPEC §7a); the binding itself is an ordinary `let`.
    LetAnn(String, TypeAnn, Expr),
    /// W01-s2: `type Name = ann`, a type alias. Parse-time metadata: the
    /// parser resolves later annotations naming `Name` into
    /// `TypeAnn::Alias`, and the statement itself is inert at runtime
    /// (the tree-walk no-ops it; the VM bridges it there). The line
    /// stamps the duplicate-alias note and fmt output.
    TypeAlias(String, TypeAnn, usize),
    Assign(String, Option<BinOp>, Expr), // name (op=)? expr
    IndexAssign(Expr, Expr, Option<BinOp>, Expr), // target[i] (op=)? expr
    MemberAssign(Expr, String, Option<BinOp>, Expr), // target.k (op=)? expr
    /// L1a: destructuring definition, `let [a, b] = e`, `let {x, y} = e`,
    /// `let [a, *rest] = e` (patterns nest).
    LetPat(Pat, Expr),
    /// L1a: destructuring for-loop, `for [k, v] in pairs { ... }`.
    ForPat(Pat, Expr, Vec<Stmt>),
    /// L1a: multiple assignment / swap, `a, b = b, a`; RHS evaluated fully
    /// (left to right) before any target is assigned. `let a, b = 1, 2` sets
    /// `define` (fresh bindings); the bare form assigns existing names.
    MultiAssign(Vec<Expr>, Vec<Expr>, bool),
    If(Vec<(Expr, Vec<Stmt>)>, Option<Vec<Stmt>>),
    While(Expr, Vec<Stmt>),
    Loop(Vec<Stmt>),
    /// W17: structured-concurrency block. Tasks spawned inside register on
    /// this scope and are joined at block exit, in spawn order, on every
    /// flow path (normal, return/break/continue, or stress).
    Scope(Vec<Stmt>),
    For(String, Expr, Vec<Stmt>),
    Return(Option<Expr>),
    Break,
    Continue,
    ExprStmt(Expr),
    /// TYPED-MODE: the match statement carries its source line so static
    /// exhaustiveness findings (T05) locate themselves.
    Match(Expr, Vec<(MatchPat, Vec<Stmt>)>, usize),
    Use(String, Option<String>),        // path, alias
    Raise(Option<String>, Expr, usize), // kind, message, statement line (W007)
    Stress {
        kind: Option<String>,
        body: Vec<Stmt>,
        rescue: Option<(Option<String>, Vec<Stmt>)>,
    },
    Gene(Arc<GeneDef>),
    Splice(Arc<SpliceDef>),
    /// W04 (SPEC §8b): `trait Name { gene m(); gene n() { … } }`.
    Trait(Arc<TraitDef>),
    /// reg-bio-3 (C9): stoichiometric RISC, `silence old -> new strength s
    /// sites n;`. The strength is the per-site capture probability (clamped
    /// 0..=1, default 1.0); each statement is one binding site (sites n
    /// composes multiplicatively: survival = (1-s)^n). Omitted strength and
    /// sites reproduce the legacy binary redirect bit-identically.
    Silence(String, Option<String>, f64, u32),
    /// reg-bio-3 (A1/A7): the polycistronic transcription unit, the
    /// namesake construct. `operon lac { lacZ rbs 1.0; lacY rbs 0.6; }`:
    /// ONE promoter drives N cistrons on ONE transcript; a call to any
    /// cistron is a transcription attempt of the WHOLE unit, so edges
    /// targeting the unit gate every member. Member order is load-bearing
    /// (RBS gradient + polarity exposure); each member's `rbs` multiplies
    /// its translation rate (Shine-Dalgarno strength, clamped 0..=1).
    Operon(String, Vec<(String, f64)>),
    Enhance(Vec<String>),
    Ires(String),
    Fate(Arc<FateDef>),
    Regulate(Vec<RegEdge>, Vec<TransEdge>, Vec<BindDef>),
    /// reg-bio-2 (A4): a small-molecule ligand pool, `ligand iptg;`.
    /// Ligands are metabolites, not genes: their levels are set via
    /// `ligand_set(name, v)` or the `.cell [ligand.<name>]` bath config,
    /// and they drive gates directly (a ligand named as an edge source is
    /// a riboswitch-style, protein-free gate).
    Ligand(String),
    /// loop-9 (C8): a quorum-sensing signal species, `autoinducer ahl;`.
    /// The species registers into the process-global SHARED medium (the
    /// environment, not the cytoplasm): `secrete` charges it, `quorum`
    /// reads it, and a species named as an edge source is a LuxR·AHL-style
    /// population gate, my secretion raises YOUR activation.
    Autoinducer(String),
    Toggle(String, String),
    /// reg-bio-2 (C11): a decoy binding site, `decoy d for tf capacity c;`.
    /// The decoy node absorbs its regulator without producing output:
    /// every regulation read of `tf` sees the free fraction
    /// max(0, level(tf) − c·level(d)), competitive titration.
    Decoy(String, String, f64),
    Repressilator(Vec<String>, Option<f64>, RepressiOverrides),
    Frame {
        name: String,
        is_proof: bool,
        body: Vec<Stmt>,
    },
    Edit(String, Vec<(String, String)>), // target, (from, to) replacements
    AnchorExport(Vec<String>),
    AnchorImport(Vec<String>),
    Tad(String, Vec<Stmt>),
    /// W025 stage 2: nested sub-module declaration, `module seq { gene x() { … } }`
    /// inside a module file (or any block). The body runs once in a fresh child
    /// scope at declaration time; the child scope's names become the sub-module's
    /// export table (a Map bound under `name`). Use paths stay file-first: a
    /// `use` tries the flat file, then descends these nested tables (SPEC §8).
    Module(String, Vec<Stmt>),
    Block(Vec<Stmt>),     // bare scoped block (Total Grammar repair product)
    Seq(Arc<GeneDef>),    // sequence definition (generator)
    Yield(Option<Expr>),  // yield inside a sequence body
    Pheno(Arc<PhenoDef>), // phenotype definition (user class)
}

#[derive(Debug, Clone, Default)]
pub struct Program {
    pub stmts: Vec<Stmt>,
    pub notes: Vec<Note>,
    /// W074: a `##` block at the very top of the file that does NOT hug a
    /// declaration (blank-line separated) becomes the module doc.
    pub module_doc: Vec<String>,
    /// proof frames gathered (file path -> is implicit)
    pub proofs: Vec<Vec<Stmt>>,
    pub named_frames: Vec<(String, Vec<Stmt>)>,
    pub anchor_exports: Vec<String>, // top-level (outside tads)
    pub tad_exports: Vec<(String, Vec<String>)>, // tad name -> exported names
    pub tad_members: Vec<(String, Vec<String>)>, // tad name -> all defined names
    pub ires: Vec<String>,
    /// W24: top-level names marked with the contextual `pub` marker.
    /// Inert by default; under `.cell modules.visibility = strict` the
    /// module exports ONLY these names (migration-safe: a strict module
    /// with zero pub marks keeps default-open, with a note).
    pub pub_exports: Vec<String>,
}

// ---------------------------------------------------- W08r statement lines

/// W08r stage 1: the first line-bearing source position reachable in an
/// expression. The AST carries lines only on the locating nodes (calls,
/// binaries, indexes, methods, propagate — dx-r2/r4), so a statement whose
/// expressions are all literals/idents reports None; the debugger then
/// falls back to cur_line. This is the extraction the VM compiler's
/// line_of stub wants too (a documented gap, not a divergence: both lanes
/// see the same None).
pub fn expr_first_line(e: &Expr) -> Option<usize> {
    match e {
        // W08r: the parser's position marker IS the line for line-silent
        // statement expressions
        Expr::At(_, l) => Some(*l),
        Expr::Call(_, _, l) => Some(*l),
        Expr::Binary(_, _, _, l) => Some(*l),
        Expr::Index(_, _, l) => Some(*l),
        Expr::Method(_, _, _, l) => Some(*l),
        Expr::MethodSafe(_, _, _, l) => Some(*l),
        Expr::Propagate(_, l) => Some(*l),
        Expr::Unary(_, b) => expr_first_line(b),
        Expr::Member(b, _) | Expr::MemberSafe(b, _) => expr_first_line(b),
        Expr::Ternary(c, _, _) => expr_first_line(c),
        Expr::List(v) => v.iter().find_map(expr_first_line),
        Expr::Map(pairs) => pairs
            .iter()
            .find_map(|(k, v)| expr_first_line(k).or_else(|| expr_first_line(v))),
        _ => None,
    }
}

impl Stmt {
    /// W08r stage 1: best-effort source line of this statement (the first
    /// line-bearing node in its expressions/heads). None = the statement
    /// is line-silent (pure literals/idents); the debug trap then falls
    /// back to the interpreter's cur_line.
    pub fn first_line(&self) -> Option<usize> {
        match self {
            Stmt::Let(_, e)
            | Stmt::LetConst(_, e)
            | Stmt::LetAnn(_, _, e)
            | Stmt::LetPat(_, e)
            | Stmt::Assign(_, _, e)
            | Stmt::ExprStmt(e)
            | Stmt::For(_, e, _)
            | Stmt::ForPat(_, e, _)
            | Stmt::While(e, _) => expr_first_line(e),
            Stmt::IndexAssign(t, i, _, e) => expr_first_line(t)
                .or_else(|| expr_first_line(i))
                .or_else(|| expr_first_line(e)),
            Stmt::MemberAssign(t, _, _, e) => expr_first_line(t).or_else(|| expr_first_line(e)),
            Stmt::MultiAssign(targets, values, _) => targets
                .iter()
                .chain(values.iter())
                .find_map(expr_first_line),
            Stmt::If(arms, _) => arms.first().and_then(|(c, _)| expr_first_line(c)),
            Stmt::Match(_e, _, l) => Some(*l),
            Stmt::Raise(_, _, l) => Some(*l),
            Stmt::TypeAlias(_, _, l) => Some(*l),
            _ => None,
        }
    }
}
