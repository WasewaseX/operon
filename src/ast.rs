//! ast.rs, Operon AST. Uses Arc throughout so gene definitions can be
//! transferred into worker threads (spawn) without Rc's thread restrictions.

use std::sync::Arc;

mod decls;
mod stmts;

pub use decls::*;
pub use stmts::*;

#[derive(Debug, Clone)]
pub struct Note {
    pub line: usize,
    pub rung: u8, // 1 canonical, 2 synonym, 3 wobble, 4 fallback
    pub message: String,
}

#[derive(Debug, Clone)]
pub enum InterpPart {
    Lit(String),
    Expr(Expr),
}

#[derive(Debug, Clone)]
pub enum Expr {
    Null,
    Bool(bool),
    Int(i64),
    Float(f64),
    Str(String),
    /// W08r: a transparent position marker. The parser wraps the RHS of a
    /// line-silent statement (pure literals/idents: nothing inside carries a
    /// source line) with `At(inner, line)` so the debugger can attribute the
    /// statement to its source line. Evaluation, compilation, lint and
    /// typecheck all pass straight through to `inner`; only the debug
    /// extractor (expr_first_line) and the VM compiler's line table read it.
    At(Box<Expr>, usize),
    /// W029: bytes literal b"...", the raw bytes after escape processing;
    /// no interpolation ever.
    Bytes(Vec<u8>),
    Interp(Vec<InterpPart>),
    List(Vec<Expr>),
    Map(Vec<(Expr, Expr)>),
    Ident(String),
    Unary(UnOp, Box<Expr>),
    /// dx-r4: source line of the operator, hard type errors locate themselves.
    Binary(BinOp, Box<Expr>, Box<Expr>, usize),
    /// A13 (dx-r2): source line of the call site, runtime builtin notes
    /// (denials, timeouts, gate changes) carry the caller's location.
    Call(Box<Expr>, Vec<Expr>, usize),
    /// dx-r4: source line of the bracket, index errors locate themselves.
    Index(Box<Expr>, Box<Expr>, usize),
    Member(Box<Expr>, String),
    /// L1a: `a?.k`, Null receiver yields Null (silent); otherwise identical
    /// to Member.
    MemberSafe(Box<Expr>, String),
    /// TYPED-MODE: source line of the method call, static member errors
    /// (`int has no method 'name'`) locate themselves like Call/Index do.
    Method(Box<Expr>, String, Vec<Expr>, usize),
    /// L1a: `a?.k(args)`, Null-safe method call (same contract).
    MethodSafe(Box<Expr>, String, Vec<Expr>, usize),
    Lambda(Arc<GeneDef>),
    Collect {
        var: String,
        iter: Box<Expr>,
        filter: Option<Box<Expr>>,
        body: Box<Expr>,
    },
    FateNew(String),
    New(String, Vec<Expr>),                   // phenotype constructor
    Ternary(Box<Expr>, Box<Expr>, Box<Expr>), // cond ? a : b
    /// W06 (D-014): `e?!`, Option/Result propagation. Some/Ok unwraps to the
    /// payload; None/Err unwinds to the nearest enclosing gene boundary and
    /// becomes that gene's return value. Line stamps the propagation signal.
    Propagate(Box<Expr>, usize),
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum UnOp {
    Neg,
    Not,
    BitNot,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum BinOp {
    Add,
    Sub,
    Mul,
    Div,
    FloorDiv,
    Mod,
    Pow,
    BitAnd,
    BitOr,
    BitXor,
    Shl,
    Shr,
    Eq,
    Neq,
    Lt,
    Le,
    Gt,
    Ge,
    And,
    Or,
    In,
    /// L1a: `a ?? b`, coalesces Null only (not falsy); right-assoc,
    /// short-circuit (b unevaluated when a is non-null).
    Nullish,
}
