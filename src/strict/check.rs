//! Type checker for the S1 strict core: the STRICT-CORE §4 rejection rules,
//! each diagnostic naming its rule. `let` lives in its own scope (depth >= 1)
//! so rule 4 can tell a let from a parameter; parameters are the assignment
//! surface (recorded reading 1 of the spec).

use super::StrictError;
use super::ast::{Expr, Stmt};
use crate::mir::{BinOp, FnSig, MirType, UnOp};
use std::collections::HashMap;

pub struct Checker<'a> {
    pub fns: &'a HashMap<String, (usize, FnSig)>,
    pub scopes: Vec<HashMap<String, MirType>>,
    pub ret: MirType,
}

const R_LET_IMMUTABLE: &str = "the strict core `let` is immutable (STRICT-CORE §2.2 rule 4); assign only function parameters";

impl<'a> Checker<'a> {
    pub fn lookup(&self, name: &str) -> Option<(usize, MirType)> {
        for (depth, scope) in self.scopes.iter().enumerate().rev() {
            if let Some(ty) = scope.get(name) {
                return Some((depth, *ty));
            }
        }
        None
    }

    pub fn check_block(&mut self, stmts: &[Stmt]) -> Result<bool, StrictError> {
        self.scopes.push(HashMap::new());
        let out = self.check_stmts(stmts);
        self.scopes.pop();
        out
    }

    /// Returns whether every path through the list terminates.
    pub fn check_stmts(&mut self, stmts: &[Stmt]) -> Result<bool, StrictError> {
        let mut terminated = false;
        for s in stmts {
            if terminated {
                let msg = "unreachable statement — every path before it already returned";
                return Err(StrictError::new(s.line(), msg));
            }
            terminated = self.check_stmt(s)?;
        }
        Ok(terminated)
    }

    fn check_stmt(&mut self, s: &Stmt) -> Result<bool, StrictError> {
        match s {
            Stmt::Let { name, ty, init, line } => self.check_let(name, ty, init, *line),
            Stmt::Assign { name, val, line } => self.check_assign(name, val, *line),
            Stmt::If { cond, then, els, line } => self.check_if(cond, then, els, *line),
            Stmt::While { cond, body, line } => self.check_while(cond, body, *line),
            Stmt::Return { val, line } => self.check_return(val, *line),
            Stmt::Expr(e) => self.check_expr_stmt(e),
        }
    }

    /// Rule 1 (duplicate binding) + rule 2 (initializer type).
    fn check_let(&mut self, name: &str, ty: &MirType, init: &Expr, line: usize) -> Result<bool, StrictError> {
        let it = self.check_expr(init)?;
        if it != *ty {
            let msg = format!("let '{name}' is declared {ty:?} but the initializer is {it:?} (STRICT-CORE §4 rule 2)");
            return Err(StrictError::new(line, msg));
        }
        let scope = self.scopes.last_mut().expect("check_let runs inside a block scope");
        if scope.contains_key(name) {
            let msg = format!("duplicate binding '{name}' in the same block (STRICT-CORE §4 rule 1)");
            return Err(StrictError::new(line, msg));
        }
        scope.insert(name.to_string(), *ty);
        Ok(false)
    }

    /// Rule 4: only parameters (scope depth 0) are assignable; rule 2 for
    /// the value type.
    fn check_assign(&mut self, name: &str, val: &Expr, line: usize) -> Result<bool, StrictError> {
        let (depth, ty) = self.lookup(name).ok_or_else(|| {
            StrictError::new(line, format!("unknown identifier '{name}' (STRICT-CORE §4 rule 1)"))
        })?;
        if depth != 0 {
            return Err(StrictError::new(
                line,
                format!("assignment to '{name}' — {R_LET_IMMUTABLE}"),
            ));
        }
        let vt = self.check_expr(val)?;
        if vt != ty {
            let msg = format!("assignment to '{name}' ({ty:?}) with a {vt:?} value (STRICT-CORE §4 rule 2)");
            return Err(StrictError::new(line, msg));
        }
        Ok(false)
    }

    /// Rule 5: conditions are Bool, no truthiness coercion. Termination is
    /// the AND of both arms (an if terminates only when each arm does).
    fn check_if(&mut self, cond: &Expr, then: &[Stmt], els: &[Stmt], line: usize) -> Result<bool, StrictError> {
        let ct = self.check_expr(cond)?;
        if ct != MirType::Bool {
            let msg = format!("if condition is {ct:?}, not Bool — no truthiness coercion in the strict core (STRICT-CORE §4 rule 5)");
            return Err(StrictError::new(line, msg));
        }
        let t_term = self.check_block(then)?;
        let e_term = self.check_block(els)?;
        Ok(t_term && e_term)
    }

    fn check_while(&mut self, cond: &Expr, body: &[Stmt], line: usize) -> Result<bool, StrictError> {
        let ct = self.check_expr(cond)?;
        if ct != MirType::Bool {
            let msg = format!("while condition is {ct:?}, not Bool — no truthiness coercion in the strict core (STRICT-CORE §4 rule 5)");
            return Err(StrictError::new(line, msg));
        }
        self.check_block(body)?;
        Ok(false) // a while never guarantees its post-state returns
    }

    /// Rule 2 for the return value; a return terminates its path.
    fn check_return(&mut self, val: &Option<Expr>, line: usize) -> Result<bool, StrictError> {
        match val {
            None => {
                if self.ret != MirType::Unit {
                    let msg = format!("return without a value in a fn returning {:?} (STRICT-CORE §4 rule 2)", self.ret);
                    return Err(StrictError::new(line, msg));
                }
            }
            Some(e) => {
                let got = self.check_expr(e)?;
                if got != self.ret {
                    let msg = format!("return value is {got:?}, the fn returns {:?} (STRICT-CORE §4 rule 2)", self.ret);
                    return Err(StrictError::new(line, msg));
                }
            }
        }
        Ok(true)
    }

    /// promote is the one statement effect; everything else is a plain
    /// expression whose value is discarded.
    fn check_expr_stmt(&mut self, e: &Expr) -> Result<bool, StrictError> {
        if let Expr::Call(name, args, line) = e {
            if name == "promote" {
                self.check_promote(args, *line)?;
                return Ok(false);
            }
        }
        self.check_expr(e)?;
        Ok(false)
    }

    pub fn check_promote(&mut self, args: &[Expr], line: usize) -> Result<(), StrictError> {
        if args.is_empty() {
            let msg = "promote needs at least one printable argument (Int | Float | Bool | Str)";
            return Err(StrictError::new(line, msg));
        }
        for a in args {
            let t = self.check_expr(a)?;
            if !matches!(t, MirType::Int | MirType::Float | MirType::Bool | MirType::Str) {
                let msg = format!("promote argument is {t:?} — Unit is not printable");
                return Err(StrictError::new(line, msg));
            }
        }
        Ok(())
    }

    pub fn check_expr(&mut self, e: &Expr) -> Result<MirType, StrictError> {
        match e {
            Expr::Int(..) => Ok(MirType::Int),
            Expr::Float(..) => Ok(MirType::Float),
            Expr::Bool(..) => Ok(MirType::Bool),
            Expr::Str(..) => Ok(MirType::Str),
            Expr::Ident(name, line) => self.check_ident(name, *line),
            Expr::Unary(op, v, line) => self.check_unary(op, v, *line),
            Expr::Bin(op, l, r, line) => self.check_bin(op, l, r, *line),
            Expr::Call(name, args, line) => self.check_call(name, args, *line),
        }
    }

    fn check_ident(&self, name: &str, line: usize) -> Result<MirType, StrictError> {
        self.lookup(name)
            .map(|(_, t)| t)
            .ok_or_else(|| StrictError::new(line, format!("unknown identifier '{name}' (STRICT-CORE §4 rule 1)")))
    }

    /// Rule 3 for unary operand homogeneity.
    fn check_unary(&mut self, op: &UnOp, v: &Expr, line: usize) -> Result<MirType, StrictError> {
        let t = self.check_expr(v)?;
        op.result_ty(t).ok_or_else(|| {
            let msg = format!("unary {op:?} on {t:?} — operands must be homogeneous (STRICT-CORE §4 rule 3)");
            StrictError::new(line, msg)
        })
    }

    /// Rules 2+3: arithmetic and comparison are homogeneous; the corpus
    /// idiom 10 == 10.0 is legacy-lane and rejected here.
    fn check_bin(&mut self, op: &BinOp, l: &Expr, r: &Expr, line: usize) -> Result<MirType, StrictError> {
        let lt = self.check_expr(l)?;
        let rt = self.check_expr(r)?;
        if lt != rt {
            let msg = format!(
                "cross-type {op:?}: {lt:?} vs {rt:?} — the strict core is homogeneous, use an explicit conversion (STRICT-CORE §4 rule 3)"
            );
            return Err(StrictError::new(line, msg));
        }
        op.result_ty(lt)
            .ok_or_else(|| StrictError::new(line, format!("{op:?} is invalid on {lt:?} (STRICT-CORE §4 rule 2)")))
    }

    /// Rule 6: known function, arity, argument types. promote is rejected in
    /// expression position (statement effect, reading 2).
    fn check_call(&mut self, name: &str, args: &[Expr], line: usize) -> Result<MirType, StrictError> {
        if name == "promote" {
            let msg = "promote is a statement effect in the strict core — it cannot appear inside an expression";
            return Err(StrictError::new(line, msg));
        }
        let (_, sig) = self.fns.get(name).ok_or_else(|| {
            StrictError::new(line, format!("call to unknown function '{name}' (STRICT-CORE §4 rule 6)"))
        })?;
        if args.len() != sig.params.len() {
            let msg = format!(
                "call to '{name}' wants {} argument(s), got {} (STRICT-CORE §4 rule 6)",
                sig.params.len(),
                args.len()
            );
            return Err(StrictError::new(line, msg));
        }
        for (i, a) in args.iter().enumerate() {
            let t = self.check_expr(a)?;
            if t != sig.params[i] {
                let msg = format!(
                    "call to '{name}' argument {} is {t:?}, wants {:?} (STRICT-CORE §4 rule 6)",
                    i + 1,
                    sig.params[i]
                );
                return Err(StrictError::new(line, msg));
            }
        }
        Ok(sig.ret)
    }
}
