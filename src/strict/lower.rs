//! Lowering from the checked strict-core AST to the typed MIR. Slot
//! discipline is deterministic (declaration order, params first — STRICT-CORE
//! §3), block shape is driven by FnBuilder + patch_term forward joins, and
//! the per-statement helpers keep every piece under the review budgets.

use super::StrictError;
use super::ast::{Expr, Stmt};
use crate::mir::{BinOp, BlockId, Const, FnBuilder, FnSig, MirFn, MirType, Operand, Terminator, UnOp};
use std::collections::HashMap;

/// One stack slot. The lowerer tracks each binding's type alongside its id so
/// expressions carry their checker-proven type through the lowering.
#[derive(Clone, Copy, Debug)]
pub struct Slot {
    pub id: u32,
    pub ty: MirType,
}

impl Slot {
    pub fn operand(self) -> Operand {
        Operand::Slot(self.id)
    }
}

pub struct Lowerer<'a> {
    pub b: FnBuilder,
    pub scopes: Vec<HashMap<String, Slot>>,
    pub fns_index: &'a HashMap<String, usize>,
    pub sigs: &'a HashMap<String, FnSig>,
    pub cur: BlockId,
    pub terminated: bool,
}

impl<'a> Lowerer<'a> {
    pub fn lookup(&self, name: &str) -> Option<Slot> {
        for scope in self.scopes.iter().rev() {
            if let Some(s) = scope.get(name) {
                return Some(*s);
            }
        }
        None
    }

    /// Closes the current block without requiring a terminator (forward
    /// joins back-patch it) and returns the new current block id.
    pub fn nbu(&mut self) -> BlockId {
        self.cur = self.b.new_block_unterminated();
        self.cur
    }

    pub fn lower_fn(
        f: &super::ast::FnDef,
        fns_index: &HashMap<String, usize>,
        sigs: &HashMap<String, FnSig>,
    ) -> Result<MirFn, StrictError> {
        let sig = FnSig {
            params: f.params.iter().map(|(_, t)| *t).collect(),
            ret: f.ret,
        };
        let mut lw = Lowerer {
            b: FnBuilder::new(&f.name, sig),
            scopes: Vec::new(),
            fns_index,
            sigs,
            cur: 0,
            terminated: false,
        };
        lw.scopes.push(HashMap::new());
        for (i, (pname, pty)) in f.params.iter().enumerate() {
            lw.scopes[0].insert(pname.clone(), Slot { id: i as u32, ty: *pty });
        }
        // body scope mirrors the checker: lets live at depth >= 1, param
        // slots stay untouched in scope 0
        lw.scopes.push(HashMap::new());
        lw.lower_stmts(&f.body)?;
        if !lw.terminated {
            // Unit functions fall off the end with an implicit `return`
            lw.b.ret(None);
        }
        Ok(lw.b.finish())
    }

    /// Each statement LIST starts reachable: the flag is per-block-list, not
    /// fn-global (a `return` in a then-arm must not leak into the else-arm).
    pub fn lower_stmts(&mut self, stmts: &[Stmt]) -> Result<(), StrictError> {
        self.terminated = false;
        for s in stmts {
            if self.terminated {
                // the checker rejects this first; unreachable here is a
                // lowering bug
                return Err(StrictError::new(s.line(), "unreachable statement"));
            }
            self.lower_stmt(s)?;
        }
        Ok(())
    }

    fn lower_stmt(&mut self, s: &Stmt) -> Result<(), StrictError> {
        match s {
            Stmt::Let { name, ty, init, .. } => self.lower_let(name, ty, init),
            Stmt::Assign { name, val, .. } => self.lower_assign(name, val),
            Stmt::If { cond, then, els, .. } => self.lower_if(cond, then, els),
            Stmt::While { cond, body, .. } => self.lower_while(cond, body),
            Stmt::Return { val, .. } => self.lower_return(val),
            Stmt::Expr(e) => self.lower_expr_stmt(e),
        }
    }

    fn lower_let(&mut self, name: &str, ty: &MirType, init: &Expr) -> Result<(), StrictError> {
        let slot = self.b.slot(*ty);
        let (o, oty) = self.lower_expr(init)?;
        debug_assert_eq!(oty, *ty, "checker proved the initializer type");
        self.write_slot(slot, o);
        self.scopes
            .last_mut()
            .expect("lower_let runs inside a block scope")
            .insert(name.to_string(), Slot { id: slot, ty: *ty });
        Ok(())
    }

    fn lower_assign(&mut self, name: &str, val: &Expr) -> Result<(), StrictError> {
        let target = self.lookup(name).expect("checker proved the name exists");
        let (o, oty) = self.lower_expr(val)?;
        debug_assert_eq!(oty, target.ty, "checker proved the value type");
        self.write_slot(target.id, o);
        Ok(())
    }

    /// LoadConst for constants, Copy for slot values — assignment is a
    /// slot-to-slot write of an owned value.
    fn write_slot(&mut self, dst: u32, o: Operand) {
        match o {
            Operand::Const(c) => {
                self.b.load_const(Some(dst), c);
            }
            Operand::Slot(src) => {
                self.b.copy(dst, src);
            }
        }
    }

    /// If-shape: pre-block Br into then/else arms; a join exists only when
    /// some arm falls through (both-arms-return needs no join — the checker
    /// guarantees nothing follows that list).
    fn lower_if(&mut self, cond: &Expr, then: &[Stmt], els: &[Stmt]) -> Result<(), StrictError> {
        let (cond, _cty) = self.lower_expr(cond)?;
        let pre = self.cur;
        let then_b = self.nbu();
        self.lower_stmts(then)?;
        let (then_end, then_term) = (self.cur, self.terminated);
        let else_b = self.nbu();
        self.lower_stmts(els)?;
        let (else_end, else_term) = (self.cur, self.terminated);
        self.b.patch_term(pre, Terminator::Br { cond, then: then_b, otherwise: else_b });
        if then_term && else_term {
            self.terminated = true;
            return Ok(());
        }
        let join = self.nbu();
        if !then_term {
            self.b.patch_term(then_end, Terminator::Jmp { target: join });
        }
        if !else_term {
            self.b.patch_term(else_end, Terminator::Jmp { target: join });
        }
        self.cur = join;
        self.terminated = false;
        Ok(())
    }

    /// While-shape: pre Jmp head; head Br body/done; body loops back to head
    /// unless it returns; done joins the continuation.
    fn lower_while(&mut self, cond: &Expr, body: &[Stmt]) -> Result<(), StrictError> {
        let pre = self.cur;
        let head = self.nbu();
        self.b.patch_term(pre, Terminator::Jmp { target: head });
        let (cond_o, _cty) = self.lower_expr(cond)?;
        let body_b = self.nbu();
        self.lower_stmts(body)?;
        let (body_end, body_term) = (self.cur, self.terminated);
        let done_b = self.nbu();
        self.b.patch_term(head, Terminator::Br { cond: cond_o, then: body_b, otherwise: done_b });
        let join = self.nbu();
        if !body_term {
            self.b.patch_term(body_end, Terminator::Jmp { target: head });
        }
        self.b.patch_term(done_b, Terminator::Jmp { target: join });
        self.cur = join;
        self.terminated = false; // done is reachable via the Br
        Ok(())
    }

    fn lower_return(&mut self, val: &Option<Expr>) -> Result<(), StrictError> {
        let o = match val {
            None => None,
            Some(e) => {
                let (o, _t) = self.lower_expr(e)?;
                Some(o)
            }
        };
        self.b.ret(o);
        self.terminated = true;
        Ok(())
    }

    /// promote is the subset's one effect: it lowers to Print. Any other
    /// expression as a statement evaluates and drops its value.
    fn lower_expr_stmt(&mut self, e: &Expr) -> Result<(), StrictError> {
        if let Expr::Call(name, args, _line) = e {
            if name == "promote" {
                let mut ops = Vec::new();
                for a in args {
                    let (o, _t) = self.lower_expr(a)?;
                    ops.push(o);
                }
                self.b.print(ops);
                return Ok(());
            }
        }
        self.lower_expr(e)?;
        Ok(())
    }

    /// Lowers one expression to an operand + its checker-proven type. The
    /// type flows through the lowering (Const::ty / Slot.ty / op result
    /// types); the validator re-checks every instruction afterwards anyway.
    pub fn lower_expr(&mut self, e: &Expr) -> Result<(Operand, MirType), StrictError> {
        Ok(match e {
            Expr::Int(v, _) => (Operand::Const(Const::Int(*v)), MirType::Int),
            Expr::Float(v, _) => (Operand::Const(Const::Float(*v)), MirType::Float),
            Expr::Bool(v, _) => (Operand::Const(Const::Bool(*v)), MirType::Bool),
            Expr::Str(v, _) => (Operand::Const(Const::Str(v.clone())), MirType::Str),
            Expr::Ident(name, _) => {
                let s = self
                    .lookup(name)
                    .ok_or_else(|| StrictError::new(0, format!("unknown identifier '{name}'")))?;
                (s.operand(), s.ty)
            }
            Expr::Unary(op, v, _) => self.lower_unary(op, v)?,
            Expr::Bin(op, l, r, _) => self.lower_bin(op, l, r)?,
            Expr::Call(name, args, line) => self.lower_call(name, args, *line)?,
        })
    }

    fn lower_unary(&mut self, op: &UnOp, v: &Expr) -> Result<(Operand, MirType), StrictError> {
        let (o, vt) = self.lower_expr(v)?;
        let ty = op
            .result_ty(vt)
            .ok_or_else(|| StrictError::new(0, format!("lowering: unary {op:?} invalid on {vt:?}")))?;
        Ok((Operand::Slot(self.b.un(None, *op, o, ty)), ty))
    }

    fn lower_bin(&mut self, op: &BinOp, l: &Expr, r: &Expr) -> Result<(Operand, MirType), StrictError> {
        let (lo, lt) = self.lower_expr(l)?;
        let (ro, rt) = self.lower_expr(r)?;
        if lt != rt {
            let msg = format!("lowering: Bin {op:?} operands {lt:?} vs {rt:?}");
            return Err(StrictError::new(0, msg));
        }
        let ty = op
            .result_ty(lt)
            .ok_or_else(|| StrictError::new(0, format!("lowering: {op:?} invalid on {lt:?}")))?;
        Ok((Operand::Slot(self.b.bin(None, *op, lo, ro, ty)), ty))
    }

    /// Direct calls only (STRICT-CORE §2.3): the callee is a module fn id.
    /// A Unit-returning call has no dst slot; its "value" operand is a unit
    /// const that can never be observed (checker rejects promoting it).
    fn lower_call(&mut self, name: &str, args: &[Expr], line: usize) -> Result<(Operand, MirType), StrictError> {
        let idx = *self
            .fns_index
            .get(name)
            .ok_or_else(|| StrictError::new(line, format!("call to unknown function '{name}'")))?;
        let sig = self.sigs.get(name).expect("checker index parity");
        let mut ops = Vec::new();
        for a in args {
            let (o, t) = self.lower_expr(a)?;
            if t != sig.params[ops.len()] {
                let msg = format!(
                    "lowering: call arg {} is {t:?}, wants {:?}",
                    ops.len() + 1,
                    sig.params[ops.len()]
                );
                return Err(StrictError::new(line, msg));
            }
            ops.push(o);
        }
        match self.b.call(None, idx as u32, ops, sig.ret) {
            Some(slot) => Ok((Operand::Slot(slot), sig.ret)),
            None => Ok((Operand::Const(Const::Unit), MirType::Unit)),
        }
    }
}
