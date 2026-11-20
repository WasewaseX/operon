//! AST for the S1 strict core (STRICT-CORE §3): every node lowers 1:1 onto
//! a `src/mir.rs` instruction family. Line spans ride on every node so the
//! §4 diagnostics name the production they reject.

use crate::mir::{BinOp, MirType, UnOp};

#[derive(Clone, Debug)]
pub enum Expr {
    Int(i64, usize),
    Float(f64, usize),
    Bool(bool, usize),
    Str(String, usize),
    Ident(String, usize),
    Unary(UnOp, Box<Expr>, usize),
    Bin(BinOp, Box<Expr>, Box<Expr>, usize),
    Call(String, Vec<Expr>, usize),
}

impl Expr {
    pub fn line(&self) -> usize {
        match self {
            Expr::Int(_, l)
            | Expr::Float(_, l)
            | Expr::Bool(_, l)
            | Expr::Str(_, l)
            | Expr::Ident(_, l)
            | Expr::Unary(_, _, l)
            | Expr::Bin(_, _, _, l)
            | Expr::Call(_, _, l) => *l,
        }
    }
}

#[derive(Clone, Debug)]
pub enum Stmt {
    Let { name: String, ty: MirType, init: Expr, line: usize },
    Assign { name: String, val: Expr, line: usize },
    If { cond: Expr, then: Vec<Stmt>, els: Vec<Stmt>, line: usize },
    While { cond: Expr, body: Vec<Stmt>, line: usize },
    Return { val: Option<Expr>, line: usize },
    Expr(Expr),
}

impl Stmt {
    pub fn line(&self) -> usize {
        match self {
            Stmt::Let { line, .. }
            | Stmt::Assign { line, .. }
            | Stmt::If { line, .. }
            | Stmt::While { line, .. }
            | Stmt::Return { line, .. } => *line,
            Stmt::Expr(e) => e.line(),
        }
    }
}

#[derive(Clone, Debug)]
pub struct FnDef {
    pub name: String,
    pub params: Vec<(String, MirType)>,
    pub ret: MirType,
    pub body: Vec<Stmt>,
    pub line: usize,
}
