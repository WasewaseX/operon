//! mir.rs — Operon v2 typed MIR: structures, builder, validator, reference
//! interpreter.
//!
//! This is the S0 seed of the v2 architecture (docs/design/NEXT.md §1–§2):
//! ONE typed middle IR that the S1 strict core lowers to, the S1 reference
//! interpreter runs, and the S2 Cranelift backend will compile. It is
//! deliberately small: the numeric-and-control subset needed by the first
//! two gates (fib, n-body), plus the two invariants the brief demands be
//! identical across every execution tier from day one:
//!
//! 1. Checked 64-bit Int arithmetic, with EXPLICIT wrapping variants
//!    (`AddWrap`/`SubWrap`/`MulWrap`) so kernels can opt into wraparound and
//!    every tier agrees on both semantics (brief §8.14, §22).
//! 2. Portable fuel budgets charged per MIR instruction (brief §31: the
//!    fuel asset evolves into a cost unit; the unit starts here, at the IR
//!    level, not at one engine's instruction set).
//!
//! What this module is NOT yet: the full v2 language. No views, effects,
//! cells, networks, no lowering from the v1 AST (that is V2-S1-A/B). It is
//! the semantic center those slices lower INTO, with a reference interpreter
//! that the differential harness will parity-check against the existing
//! engines on the S1 corpus slice.
//!
//! Values here have no shared mutability (no `Rc<RefCell>`): operands are
//! slots in one frame, calls pass owned values, and the interpreter is the
//! semantic reference — speed is NOT its job (the dev JIT and the release
//! backend exist for that).

use std::fmt;

/// Slot index inside one function frame.
pub type SlotId = u32;
/// Function index inside a module.
pub type FnId = u32;
/// Block index inside one function (block 0 is the entry).
pub type BlockId = u32;

/// Hard call-depth cap. A portable budget, not an engine accident: the same
/// cap must hold in the JIT and the release tier (recorded in docs/design/MIR.md).
pub const MAX_CALL_DEPTH: u32 = 10_000;

// ---------------------------------------------------------------------------
// types and constants
// ---------------------------------------------------------------------------

/// The typed core's scalar types. Grows with the strict core subset
/// (V2-S1-A: lists, options, results); grows ONLY with a type.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MirType {
    /// Checked 64-bit signed integer.
    Int,
    /// IEEE-754 binary64.
    Float,
    Bool,
    Str,
    Unit,
}

#[derive(Clone, Debug, PartialEq)]
pub enum Const {
    Int(i64),
    Float(f64),
    Bool(bool),
    Str(String),
    Unit,
}

impl Const {
    pub fn ty(&self) -> MirType {
        match self {
            Const::Int(_) => MirType::Int,
            Const::Float(_) => MirType::Float,
            Const::Bool(_) => MirType::Bool,
            Const::Str(_) => MirType::Str,
            Const::Unit => MirType::Unit,
        }
    }
}

// ---------------------------------------------------------------------------
// instructions
// ---------------------------------------------------------------------------

/// Binary operators. Arithmetic on `Int` is CHECKED unless the op is an
/// explicit `*Wrap` variant — the wrapping choice lives in the IR, so every
/// backend (interpreter, Cranelift, LLVM) lowers the same semantics.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum BinOp {
    Add,
    AddWrap,
    Sub,
    SubWrap,
    Mul,
    MulWrap,
    Div,
    Rem,
    Eq,
    Ne,
    Lt,
    Le,
    Gt,
    Ge,
    And,
    Or,
}

impl BinOp {
    /// Explicitly wrapping integer arithmetic (kernel opt-in).
    pub fn is_wrapping(self) -> bool {
        matches!(self, BinOp::AddWrap | BinOp::SubWrap | BinOp::MulWrap)
    }

    pub fn is_arith(self) -> bool {
        matches!(
            self,
            BinOp::Add
                | BinOp::AddWrap
                | BinOp::Sub
                | BinOp::SubWrap
                | BinOp::Mul
                | BinOp::MulWrap
                | BinOp::Div
                | BinOp::Rem
        )
    }

    pub fn is_cmp(self) -> bool {
        matches!(
            self,
            BinOp::Eq | BinOp::Ne | BinOp::Lt | BinOp::Le | BinOp::Gt | BinOp::Ge
        )
    }

    pub fn is_logic(self) -> bool {
        matches!(self, BinOp::And | BinOp::Or)
    }

    /// Result type of `lhs op rhs` given a matching operand type, or None if
    /// the operand type is invalid for this op.
    pub fn result_ty(self, operand: MirType) -> Option<MirType> {
        match self {
            BinOp::Add
            | BinOp::AddWrap
            | BinOp::Sub
            | BinOp::SubWrap
            | BinOp::Mul
            | BinOp::MulWrap
            | BinOp::Div
            | BinOp::Rem => match operand {
                MirType::Int | MirType::Float => Some(operand),
                _ => None,
            },
            BinOp::Eq | BinOp::Ne => Some(MirType::Bool),
            BinOp::Lt | BinOp::Le | BinOp::Gt | BinOp::Ge => match operand {
                MirType::Int | MirType::Float | MirType::Str => Some(MirType::Bool),
                _ => None,
            },
            BinOp::And | BinOp::Or => match operand {
                MirType::Bool => Some(MirType::Bool),
                _ => None,
            },
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum UnOp {
    Neg,
    Not,
}

impl UnOp {
    pub fn result_ty(self, operand: MirType) -> Option<MirType> {
        match self {
            UnOp::Neg => match operand {
                MirType::Int | MirType::Float => Some(operand),
                _ => None,
            },
            UnOp::Not => match operand {
                MirType::Bool => Some(MirType::Bool),
                _ => None,
            },
        }
    }
}

/// An instruction operand: a constant or a frame slot.
#[derive(Clone, Debug, PartialEq)]
pub enum Operand {
    Const(Const),
    Slot(SlotId),
}

impl Operand {
    fn ty(&self, slot_tys: &[MirType]) -> Option<MirType> {
        match self {
            Operand::Const(c) => Some(c.ty()),
            Operand::Slot(s) => slot_tys.get(*s as usize).copied(),
        }
    }
}

/// One non-terminating instruction.
#[derive(Clone, Debug, PartialEq)]
pub enum Instr {
    LoadConst {
        dst: SlotId,
        val: Const,
    },
    /// Slot-to-slot move (values are owned; the source slot becomes dead).
    Copy {
        dst: SlotId,
        src: SlotId,
    },
    Bin {
        dst: SlotId,
        op: BinOp,
        lhs: Operand,
        rhs: Operand,
    },
    Un {
        dst: SlotId,
        op: UnOp,
        v: Operand,
    },
    /// Direct call to another function in the same module. Direct calls only
    /// in the strict core: indirect calls (function pointers) arrive with
    /// explicit effect annotations (brief §8.5) and are not part of S0/S1.
    Call {
        dst: Option<SlotId>,
        callee: FnId,
        args: Vec<Operand>,
    },
    /// The S1 print surface: `promote(...)` lowers here (V2-S1-B). One
    /// charged op; the rendered line lands in `Interp::out` with legacy
    /// promote display parity. The S4 suspension family generalizes it.
    Print {
        args: Vec<Operand>,
    },
}

/// Every block ends in exactly one terminator. Suspension points (brief
/// §12: visible at call sites) will enter here as their own terminator
/// family in S4; the S0/S1 core subset is pure CPU code and suspends nothing.
#[derive(Clone, Debug, PartialEq)]
pub enum Terminator {
    Ret {
        val: Option<Operand>,
    },
    Jmp {
        target: BlockId,
    },
    Br {
        cond: Operand,
        then: BlockId,
        otherwise: BlockId,
    },
}

#[derive(Clone, Debug, PartialEq)]
pub struct Block {
    pub instrs: Vec<Instr>,
    pub term: Terminator,
}

#[derive(Clone, Debug, PartialEq)]
pub struct FnSig {
    pub params: Vec<MirType>,
    pub ret: MirType,
}

#[derive(Clone, Debug)]
pub struct MirFn {
    pub name: String,
    pub sig: FnSig,
    /// Frame slot count; slot types are indexed by slot id (params first).
    pub slot_tys: Vec<MirType>,
    pub blocks: Vec<Block>,
}

#[derive(Clone, Debug, Default)]
pub struct Module {
    pub fns: Vec<MirFn>,
}

impl Module {
    pub fn fn_by_name(&self, name: &str) -> Option<FnId> {
        self.fns
            .iter()
            .position(|f| f.name == name)
            .map(|i| i as FnId)
    }

    /// Type-checks the whole module: block ids in range, call targets and
    /// arities valid, every instruction type-correct, terminators type-
    /// correct, return slots match the signature. This is what makes the MIR
    /// TYPED rather than merely shaped; backends may trust it.
    pub fn validate(&self) -> Result<(), MirError> {
        for (fi, f) in self.fns.iter().enumerate() {
            if f.blocks.is_empty() {
                return Err(MirError::InvalidModule(format!(
                    "fn {} (#{fi}) has no blocks",
                    f.name
                )));
            }
            for (bi, b) in f.blocks.iter().enumerate() {
                for ins in &b.instrs {
                    self.check_instr(f, fi, ins)?;
                }
                match &b.term {
                    Terminator::Ret { val } => match val {
                        Some(o) => {
                            let t = o.ty(&f.slot_tys).ok_or_else(|| {
                                MirError::InvalidModule(format!(
                                    "fn {} block {bi}: ret operand slot out of range",
                                    f.name
                                ))
                            })?;
                            if t != f.sig.ret {
                                return Err(MirError::InvalidModule(format!(
                                    "fn {} block {bi}: returns {t:?}, signature wants {:?}",
                                    f.name, f.sig.ret
                                )));
                            }
                        }
                        None => {
                            if f.sig.ret != MirType::Unit {
                                return Err(MirError::InvalidModule(format!(
                                    "fn {} block {bi}: non-Unit fn returns no value",
                                    f.name
                                )));
                            }
                        }
                    },
                    Terminator::Jmp { target } => {
                        if *target as usize >= f.blocks.len() {
                            return Err(MirError::InvalidModule(format!(
                                "fn {} block {bi}: jmp target {target} out of range",
                                f.name
                            )));
                        }
                    }
                    Terminator::Br {
                        cond,
                        then,
                        otherwise,
                    } => {
                        if cond.ty(&f.slot_tys) != Some(MirType::Bool) {
                            return Err(MirError::InvalidModule(format!(
                                "fn {} block {bi}: br condition is not Bool",
                                f.name
                            )));
                        }
                        if *then as usize >= f.blocks.len() || *otherwise as usize >= f.blocks.len()
                        {
                            return Err(MirError::InvalidModule(format!(
                                "fn {} block {bi}: br target out of range",
                                f.name
                            )));
                        }
                    }
                }
                // Reachability of non-entry blocks is a lint for the DCE pass
                // that lands with V2-S1-B, not a type error; noted here so
                // nobody mistakes validate() for the full pass set.
            }
        }
        Ok(())
    }

    fn check_instr(&self, f: &MirFn, fi: usize, ins: &Instr) -> Result<(), MirError> {
        let bad = |msg: String| MirError::InvalidModule(format!("fn {} (#{fi}): {msg}", f.name));
        let slot_ty = |s: SlotId| -> Result<MirType, MirError> {
            f.slot_tys
                .get(s as usize)
                .copied()
                .ok_or_else(|| bad(format!("slot {s} out of range")))
        };
        match ins {
            Instr::LoadConst { dst, val } => {
                if slot_ty(*dst)? != val.ty() {
                    return Err(bad(format!(
                        "LoadConst {:?} into slot of type {:?}",
                        val.ty(),
                        slot_ty(*dst)?
                    )));
                }
            }
            Instr::Copy { dst, src } => {
                if slot_ty(*dst)? != slot_ty(*src)? {
                    return Err(bad("Copy between slots of different types".to_string()));
                }
            }
            Instr::Bin { dst, op, lhs, rhs } => {
                let lt = lhs
                    .ty(&f.slot_tys)
                    .ok_or_else(|| bad("Bin lhs slot out of range".to_string()))?;
                let rt = rhs
                    .ty(&f.slot_tys)
                    .ok_or_else(|| bad("Bin rhs slot out of range".to_string()))?;
                if lt != rt {
                    return Err(bad(format!("Bin {op:?} operand mismatch {lt:?} vs {rt:?}")));
                }
                let want = op
                    .result_ty(lt)
                    .ok_or_else(|| bad(format!("Bin {op:?} invalid operand type {lt:?}")))?;
                if slot_ty(*dst)? != want {
                    return Err(bad(format!(
                        "Bin {op:?} dst is {:?}, op produces {want:?}",
                        slot_ty(*dst)?
                    )));
                }
            }
            Instr::Un { dst, op, v } => {
                let t = v
                    .ty(&f.slot_tys)
                    .ok_or_else(|| bad("Un operand slot out of range".to_string()))?;
                let want = op
                    .result_ty(t)
                    .ok_or_else(|| bad(format!("Un {op:?} invalid operand type {t:?}")))?;
                if slot_ty(*dst)? != want {
                    return Err(bad("Un dst type mismatch".to_string()));
                }
            }
            Instr::Call { dst, callee, args } => {
                let callee_fn = self
                    .fns
                    .get(*callee as usize)
                    .ok_or_else(|| bad(format!("call target #{callee} out of range")))?;
                if args.len() != callee_fn.sig.params.len() {
                    return Err(bad(format!(
                        "call to {} wants {} args, got {}",
                        callee_fn.name,
                        callee_fn.sig.params.len(),
                        args.len()
                    )));
                }
                for (i, a) in args.iter().enumerate() {
                    let t = a
                        .ty(&f.slot_tys)
                        .ok_or_else(|| bad(format!("call arg {i} slot out of range")))?;
                    if t != callee_fn.sig.params[i] {
                        return Err(bad(format!(
                            "call to {} arg {i} is {t:?}, wants {:?}",
                            callee_fn.name, callee_fn.sig.params[i]
                        )));
                    }
                }
                match dst {
                    Some(d) => {
                        if slot_ty(*d)? != callee_fn.sig.ret {
                            return Err(bad(format!(
                                "call to {} dst is {:?}, returns {:?}",
                                callee_fn.name,
                                slot_ty(*d)?,
                                callee_fn.sig.ret
                            )));
                        }
                    }
                    None => {
                        if callee_fn.sig.ret != MirType::Unit {
                            return Err(bad(format!(
                                "call to {} returns a value but dst is None",
                                callee_fn.name
                            )));
                        }
                    }
                }
            }
            Instr::Print { args } => {
                for (i, a) in args.iter().enumerate() {
                    let t = a
                        .ty(&f.slot_tys)
                        .ok_or_else(|| bad(format!("print arg {i} slot out of range")))?;
                    if !matches!(
                        t,
                        MirType::Int | MirType::Float | MirType::Bool | MirType::Str
                    ) {
                        return Err(bad(format!(
                            "print arg {i} is {t:?} — Unit is not printable"
                        )));
                    }
                }
            }
        }
        Ok(())
    }
}

// ---------------------------------------------------------------------------
// builder
// ---------------------------------------------------------------------------

/// Builds one [`MirFn`] block by block. Slots are declared (and typed) up
/// front so the validator can type-check every instruction; the builder
/// never invents implicit types.
pub struct FnBuilder {
    name: String,
    sig: FnSig,
    slot_tys: Vec<MirType>,
    blocks: Vec<Block>,
    cur_instrs: Vec<Instr>,
    cur_term: Option<Terminator>,
    /// Closed blocks whose terminator is still the pending sentinel —
    /// patch_term clears entries; finish() refuses to publish with any left.
    pending_terms: Vec<BlockId>,
}

impl FnBuilder {
    pub fn new(name: &str, sig: FnSig) -> FnBuilder {
        let slot_tys: Vec<MirType> = sig.params.clone();
        FnBuilder {
            name: name.to_string(),
            sig,
            slot_tys,
            blocks: Vec::new(),
            cur_instrs: Vec::new(),
            cur_term: None,
            pending_terms: Vec::new(),
        }
    }

    /// Declares a new typed slot; the id is its index.
    pub fn slot(&mut self, ty: MirType) -> SlotId {
        self.slot_tys.push(ty);
        (self.slot_tys.len() - 1) as SlotId
    }

    /// Parameter slots occupy ids 0..n in order.
    pub fn param(&self, i: usize) -> SlotId {
        i as SlotId
    }

    pub fn load_const(&mut self, dst: Option<SlotId>, val: Const) -> SlotId {
        let d = match dst {
            Some(d) => d,
            None => self.slot(val.ty()),
        };
        self.cur_instrs.push(Instr::LoadConst { dst: d, val });
        d
    }

    pub fn copy(&mut self, dst: SlotId, src: SlotId) {
        self.cur_instrs.push(Instr::Copy { dst, src });
    }

    /// Emits the subset's one effect: the strict-core print (V2-S1-B). One
    /// charged op at run time; the rendered line lands in `Interp::out`.
    pub fn print(&mut self, args: Vec<Operand>) {
        self.cur_instrs.push(Instr::Print { args });
    }

    /// Closes the current block WITHOUT requiring a terminator; the closed
    /// block stays PENDING in `pending_terms` until patch_term sets it. The
    /// strict lowering drives if/while shape with this: a forgotten patch
    /// panics in finish() instead of publishing a corrupt module.
    pub fn new_block_unterminated(&mut self) -> BlockId {
        let term = self.cur_term.take();
        let had_term = term.is_some();
        let id = self.blocks.len() as BlockId;
        let closed = Block {
            instrs: std::mem::take(&mut self.cur_instrs),
            // Jmp-to-self marks a pending slot: lowering-produced shapes never
            // legitimately self-jump (branch targets are always other blocks),
            // and the pending ledger forces patch_term before finish().
            term: term.unwrap_or(Terminator::Jmp { target: id }),
        };
        self.blocks.push(closed);
        if !had_term {
            self.pending_terms.push(id);
        }
        self.blocks.len() as BlockId
    }

    pub fn bin(
        &mut self,
        dst: Option<SlotId>,
        op: BinOp,
        lhs: Operand,
        rhs: Operand,
        result_ty: MirType,
    ) -> SlotId {
        let d = match dst {
            Some(d) => d,
            None => self.slot(result_ty),
        };
        self.cur_instrs.push(Instr::Bin {
            dst: d,
            op,
            lhs,
            rhs,
        });
        d
    }

    pub fn un(&mut self, dst: Option<SlotId>, op: UnOp, v: Operand, result_ty: MirType) -> SlotId {
        let d = match dst {
            Some(d) => d,
            None => self.slot(result_ty),
        };
        self.cur_instrs.push(Instr::Un { dst: d, op, v });
        d
    }

    pub fn call(
        &mut self,
        dst: Option<SlotId>,
        callee: FnId,
        args: Vec<Operand>,
        ret_ty: MirType,
    ) -> Option<SlotId> {
        let d = match dst {
            Some(d) => Some(d),
            None if ret_ty == MirType::Unit => None,
            None => Some(self.slot(ret_ty)),
        };
        self.cur_instrs.push(Instr::Call {
            dst: d,
            callee,
            args,
        });
        d
    }

    /// Closes the current block (it must already be terminated) and starts a
    /// new empty one; returns the new block's id.
    pub fn new_block(&mut self) -> BlockId {
        let closed = Block {
            instrs: std::mem::take(&mut self.cur_instrs),
            term: self
                .cur_term
                .take()
                .expect("previous block must be terminated before new_block"),
        };
        self.blocks.push(closed);
        self.blocks.len() as BlockId
    }

    /// Overwrites the terminator of an already-closed block. The strict-core
    /// lowering pass (src/strict.rs, V2-S1-B) needs this for forward joins:
    /// an if-arm's fall-through block is closed before the join block it
    /// must jump to exists. Patching also clears the block's pending status.
    pub fn patch_term(&mut self, block: BlockId, term: Terminator) {
        let b = self
            .blocks
            .get_mut(block as usize)
            .unwrap_or_else(|| panic!("patch_term: block {block} not yet closed"));
        b.term = term;
        self.pending_terms.retain(|&p| p != block);
    }

    pub fn ret(&mut self, val: Option<Operand>) {
        self.cur_term = Some(Terminator::Ret { val });
    }

    pub fn jmp(&mut self, target: BlockId) {
        self.cur_term = Some(Terminator::Jmp { target });
    }

    pub fn br(&mut self, cond: Operand, then: BlockId, otherwise: BlockId) {
        self.cur_term = Some(Terminator::Br {
            cond,
            then,
            otherwise,
        });
    }

    pub fn finish(mut self) -> MirFn {
        assert!(
            self.pending_terms.is_empty(),
            "lowering bug: block(s) {:?} never got their terminator (patch_term) before finish",
            self.pending_terms
        );
        if !self.cur_instrs.is_empty() || self.cur_term.is_some() {
            self.blocks.push(Block {
                instrs: std::mem::take(&mut self.cur_instrs),
                term: self
                    .cur_term
                    .take()
                    .unwrap_or(Terminator::Ret { val: None }),
            });
        }
        MirFn {
            name: self.name,
            sig: self.sig,
            slot_tys: self.slot_tys,
            blocks: self.blocks,
        }
    }
}

// ---------------------------------------------------------------------------
// values and the reference interpreter
// ---------------------------------------------------------------------------

#[derive(Clone, Debug, PartialEq)]
pub enum Value {
    Int(i64),
    Float(f64),
    Bool(bool),
    Str(String),
    Unit,
}

impl Value {
    pub fn ty(&self) -> MirType {
        match self {
            Value::Int(_) => MirType::Int,
            Value::Float(_) => MirType::Float,
            Value::Bool(_) => MirType::Bool,
            Value::Str(_) => MirType::Str,
            Value::Unit => MirType::Unit,
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub enum MirError {
    /// Fuel exhausted: the portable budget contract, identical in every tier.
    OutOfFuel {
        charged: u64,
    },
    /// Checked integer arithmetic overflowed. Wrapping kernels use the
    /// explicit `*Wrap` ops and never see this.
    Overflow {
        op: BinOp,
    },
    DivideByZero,
    /// Call depth exceeded MAX_CALL_DEPTH.
    StackOverflow {
        depth: u32,
    },
    /// Module failed validation.
    InvalidModule(String),
    /// Entry signature mismatch against provided args.
    ArgMismatch {
        expected: Vec<MirType>,
        got: Vec<MirType>,
    },
    /// A slot held a value of the wrong type at run time (validator bug guard).
    TypeMismatch {
        want: MirType,
        got: MirType,
    },
}

impl fmt::Display for MirError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            MirError::OutOfFuel { charged } => {
                write!(f, "MIR out of fuel after {charged} charged ops")
            }
            MirError::Overflow { op } => write!(f, "checked integer overflow in {op:?}"),
            MirError::DivideByZero => write!(f, "integer divide by zero"),
            MirError::StackOverflow { depth } => write!(
                f,
                "call depth {depth} exceeds the portable cap {MAX_CALL_DEPTH}"
            ),
            MirError::InvalidModule(msg) => write!(f, "invalid MIR module: {msg}"),
            MirError::ArgMismatch { expected, got } => {
                write!(f, "entry arg mismatch: wants {expected:?}, got {got:?}")
            }
            MirError::TypeMismatch { want, got } => {
                write!(f, "slot type mismatch: want {want:?}, got {got:?}")
            }
        }
    }
}

/// One activation record. Slots hold owned values; `ret_dst` is the caller's
/// destination slot for this frame's return value (the return register).
struct Frame {
    f: FnId,
    slots: Vec<Value>,
    block: BlockId,
    ip: usize,
    ret_dst: Option<SlotId>,
}

/// The reference interpreter over the typed MIR. Also the compile-time
/// evaluator for deterministic macros once those land (brief §16) — the
/// same code path, the same semantics. Fuel is charged per executed
/// instruction; terminators are free.
pub struct Interp {
    /// Fuel budget; `u64::MAX` means unbounded (tests only — production
    /// always charges a budget).
    pub fuel: u64,
    charged: u64,
    /// Printed lines (the `Print` sink): buffered so the differential lane
    /// compares them byte-for-byte regardless of process plumbing.
    pub out: Vec<String>,
}

impl Interp {
    pub fn with_fuel(fuel: u64) -> Interp {
        Interp {
            fuel,
            charged: 0,
            out: Vec::new(),
        }
    }

    /// Ops charged so far (the portable cost unit: one MIR instruction).
    pub fn charged(&self) -> u64 {
        self.charged
    }

    /// Validates, then executes `module.fns[entry]` with `args`.
    pub fn run(
        &mut self,
        module: &Module,
        entry: FnId,
        args: Vec<Value>,
    ) -> Result<Value, MirError> {
        module.validate()?;
        let f0 = module
            .fns
            .get(entry as usize)
            .ok_or_else(|| MirError::InvalidModule(format!("entry fn #{entry} out of range")))?;
        let got: Vec<MirType> = args.iter().map(|v| v.ty()).collect();
        if got != f0.sig.params {
            return Err(MirError::ArgMismatch {
                expected: f0.sig.params.clone(),
                got,
            });
        }
        let mut stack: Vec<Frame> = Vec::new();
        stack.push(Frame {
            f: entry,
            slots: fresh_slots(f0, args),
            block: 0,
            ip: 0,
            ret_dst: None,
        });

        loop {
            // fetch phase: read-only borrows of module + stack top
            let (fid, block, ip) = {
                let fr = stack.last().expect("frame stack never empty inside run");
                (fr.f, fr.block, fr.ip)
            };
            let fdata = &module.fns[fid as usize];
            let blk = &fdata.blocks[block as usize];

            if ip < blk.instrs.len() {
                self.charge()?;
                let ins = blk.instrs[ip].clone();
                match ins {
                    Instr::LoadConst { dst, val } => {
                        let fr = stack.last_mut().expect("frame present");
                        fr.slots[dst as usize] = const_to_value(val);
                        fr.ip += 1;
                    }
                    Instr::Copy { dst, src } => {
                        let fr = stack.last_mut().expect("frame present");
                        let v = fr.slots[src as usize].clone();
                        fr.slots[dst as usize] = v;
                        fr.ip += 1;
                    }
                    Instr::Bin { dst, op, lhs, rhs } => {
                        let (l, r) = {
                            let fr = stack.last().expect("frame present");
                            (
                                read_operand(fr, lhs.clone())?,
                                read_operand(fr, rhs.clone())?,
                            )
                        };
                        let v = self.eval_bin(op, l, r)?;
                        let fr = stack.last_mut().expect("frame present");
                        fr.slots[dst as usize] = v;
                        fr.ip += 1;
                    }
                    Instr::Un { dst, op, v } => {
                        let x = {
                            let fr = stack.last().expect("frame present");
                            read_operand(fr, v.clone())?
                        };
                        let out = eval_un(op, x)?;
                        let fr = stack.last_mut().expect("frame present");
                        fr.slots[dst as usize] = out;
                        fr.ip += 1;
                    }
                    Instr::Call { dst, callee, args } => {
                        if stack.len() >= MAX_CALL_DEPTH as usize {
                            return Err(MirError::StackOverflow {
                                depth: stack.len() as u32,
                            });
                        }
                        let vals = {
                            let fr = stack.last().expect("frame present");
                            let mut vals = Vec::with_capacity(args.len());
                            for a in &args {
                                vals.push(read_operand(fr, a.clone())?);
                            }
                            vals
                        };
                        let cf = &module.fns[callee as usize];
                        stack.push(Frame {
                            f: callee,
                            slots: fresh_slots(cf, vals),
                            block: 0,
                            ip: 0,
                            ret_dst: dst,
                        });
                        // caller ip advances when its frame resumes
                        let n = stack.len();
                        if n >= 2 {
                            stack[n - 2].ip += 1;
                        }
                        continue;
                    }
                    Instr::Print { args } => {
                        let line = {
                            let fr = stack.last().expect("frame present");
                            let parts = args
                                .iter()
                                .map(|a| {
                                    read_operand(fr, a.clone())
                                        .map(|v| format_mir_value(&v))
                                })
                                .collect::<Result<Vec<_>, _>>()?;
                            parts.join(" ")
                        };
                        self.out.push(line);
                        let fr = stack.last_mut().expect("frame present");
                        fr.ip += 1;
                    }
                }
                continue;
            }

            // terminator phase
            let term = blk.term.clone();
            match term {
                Terminator::Ret { val } => {
                    let fr = stack
                        .pop()
                        .ok_or_else(|| MirError::InvalidModule("popped last frame".into()))?;
                    let v = match val {
                        Some(o) => read_operand(&fr, o)?,
                        None => Value::Unit,
                    };
                    match stack.last_mut() {
                        None => return Ok(v),
                        Some(caller) => {
                            if let Some(d) = fr.ret_dst {
                                caller.slots[d as usize] = v;
                            }
                        }
                    }
                }
                Terminator::Jmp { target } => {
                    let fr = stack.last_mut().expect("frame present");
                    fr.block = target;
                    fr.ip = 0;
                }
                Terminator::Br {
                    cond,
                    then,
                    otherwise,
                } => {
                    let c = {
                        let fr = stack.last().expect("frame present");
                        read_operand(fr, cond.clone())?
                    };
                    let Value::Bool(b) = c else {
                        return Err(MirError::TypeMismatch {
                            want: MirType::Bool,
                            got: c.ty(),
                        });
                    };
                    let fr = stack.last_mut().expect("frame present");
                    fr.block = if b { then } else { otherwise };
                    fr.ip = 0;
                }
            }
        }
    }

    fn charge(&mut self) -> Result<(), MirError> {
        self.charged += 1;
        if self.charged > self.fuel {
            return Err(MirError::OutOfFuel {
                charged: self.charged,
            });
        }
        Ok(())
    }

    fn eval_bin(&mut self, op: BinOp, l: Value, r: Value) -> Result<Value, MirError> {
        use BinOp::*;
        let ov = |op| MirError::Overflow { op };
        Ok(match (op, l, r) {
            (Add, Value::Int(a), Value::Int(b)) => Value::Int(a.checked_add(b).ok_or(ov(Add))?),
            (AddWrap, Value::Int(a), Value::Int(b)) => Value::Int(a.wrapping_add(b)),
            (Sub, Value::Int(a), Value::Int(b)) => Value::Int(a.checked_sub(b).ok_or(ov(Sub))?),
            (SubWrap, Value::Int(a), Value::Int(b)) => Value::Int(a.wrapping_sub(b)),
            (Mul, Value::Int(a), Value::Int(b)) => Value::Int(a.checked_mul(b).ok_or(ov(Mul))?),
            (MulWrap, Value::Int(a), Value::Int(b)) => Value::Int(a.wrapping_mul(b)),
            (Div, Value::Int(a), Value::Int(b)) => {
                if b == 0 {
                    return Err(MirError::DivideByZero);
                }
                Value::Int(a.checked_div(b).ok_or(ov(Div))?)
            }
            (Rem, Value::Int(a), Value::Int(b)) => {
                if b == 0 {
                    return Err(MirError::DivideByZero);
                }
                Value::Int(a.checked_rem(b).ok_or(ov(Rem))?)
            }
            (Add, Value::Float(a), Value::Float(b)) => Value::Float(a + b),
            (Sub, Value::Float(a), Value::Float(b)) => Value::Float(a - b),
            (Mul, Value::Float(a), Value::Float(b)) => Value::Float(a * b),
            (Div, Value::Float(a), Value::Float(b)) => Value::Float(a / b),
            (Eq, Value::Int(a), Value::Int(b)) => Value::Bool(a == b),
            (Eq, Value::Float(a), Value::Float(b)) => Value::Bool(a == b),
            (Eq, Value::Bool(a), Value::Bool(b)) => Value::Bool(a == b),
            (Eq, Value::Str(a), Value::Str(b)) => Value::Bool(a == b),
            (Ne, Value::Int(a), Value::Int(b)) => Value::Bool(a != b),
            (Ne, Value::Float(a), Value::Float(b)) => Value::Bool(a != b),
            (Ne, Value::Bool(a), Value::Bool(b)) => Value::Bool(a != b),
            (Ne, Value::Str(a), Value::Str(b)) => Value::Bool(a != b),
            (Lt, Value::Int(a), Value::Int(b)) => Value::Bool(a < b),
            (Le, Value::Int(a), Value::Int(b)) => Value::Bool(a <= b),
            (Gt, Value::Int(a), Value::Int(b)) => Value::Bool(a > b),
            (Ge, Value::Int(a), Value::Int(b)) => Value::Bool(a >= b),
            (Lt, Value::Float(a), Value::Float(b)) => Value::Bool(a < b),
            (Le, Value::Float(a), Value::Float(b)) => Value::Bool(a <= b),
            (Gt, Value::Float(a), Value::Float(b)) => Value::Bool(a > b),
            (Ge, Value::Float(a), Value::Float(b)) => Value::Bool(a >= b),
            (Lt, Value::Str(a), Value::Str(b)) => Value::Bool(a < b),
            (Le, Value::Str(a), Value::Str(b)) => Value::Bool(a <= b),
            (Gt, Value::Str(a), Value::Str(b)) => Value::Bool(a > b),
            (Ge, Value::Str(a), Value::Str(b)) => Value::Bool(a >= b),
            (And, Value::Bool(a), Value::Bool(b)) => Value::Bool(a && b),
            (Or, Value::Bool(a), Value::Bool(b)) => Value::Bool(a || b),
            (_op, l, r) => {
                return Err(MirError::TypeMismatch {
                    want: l.ty(),
                    got: r.ty(),
                })
            }
        })
    }
}

fn fresh_slots(f: &MirFn, args: Vec<Value>) -> Vec<Value> {
    let mut slots = vec![Value::Unit; f.slot_tys.len()];
    for (i, v) in args.into_iter().enumerate() {
        slots[i] = v;
    }
    slots
}

fn read_operand(frame: &Frame, o: Operand) -> Result<Value, MirError> {
    match o {
        Operand::Const(c) => Ok(const_to_value(c)),
        Operand::Slot(s) => frame
            .slots
            .get(s as usize)
            .cloned()
            .ok_or_else(|| MirError::InvalidModule(format!("slot {s} out of range"))),
    }
}

fn eval_un(op: UnOp, x: Value) -> Result<Value, MirError> {
    Ok(match (op, x) {
        (UnOp::Neg, Value::Int(a)) => Value::Int(
            a.checked_neg()
                .ok_or(MirError::Overflow { op: BinOp::Sub })?,
        ),
        (UnOp::Neg, Value::Float(a)) => Value::Float(-a),
        (UnOp::Not, Value::Bool(a)) => Value::Bool(!a),
        (op, v) => {
            return Err(MirError::TypeMismatch {
                want: match op {
                    UnOp::Neg => MirType::Int,
                    UnOp::Not => MirType::Bool,
                },
                got: v.ty(),
            })
        }
    })
}

fn const_to_value(c: Const) -> Value {
    match c {
        Const::Int(v) => Value::Int(v),
        Const::Float(v) => Value::Float(v),
        Const::Bool(v) => Value::Bool(v),
        Const::Str(v) => Value::Str(v),
        Const::Unit => Value::Unit,
    }
}

/// Display-format parity with the legacy engine's promote builtin
/// (src/value.rs `Value::display`: strings raw, everything else repr).
/// Floats go through the SAME formatter (`crate::value::format_float`), so
/// the S1 differential lane compares identical bytes, not similar ones.
fn format_mir_value(v: &Value) -> String {
    match v {
        Value::Str(s) => s.clone(),
        Value::Int(i) => i.to_string(),
        Value::Bool(true) => "true".into(),
        Value::Bool(false) => "false".into(),
        Value::Float(f) => crate::value::format_float(*f),
        // Unreachable through validate() (Print rejects Unit operands);
        // kept so the match stays total if the checker is ever bypassed.
        Value::Unit => "unit".into(),
    }
}

// ---------------------------------------------------------------------------
// tests — the S0 parity seed: every test pairs the MIR program against a
// native Rust reference implementation of the same semantics, which is the
// differential discipline the S1 harness will scale to the corpus.
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn fib_builder() -> (Module, FnId) {
        // fn fib(n: Int) -> Int { if n < 2 { n } else { fib(n-1) + fib(n-2) } }
        let mut b = FnBuilder::new(
            "fib",
            FnSig {
                params: vec![MirType::Int],
                ret: MirType::Int,
            },
        );
        let n = b.param(0);
        let two = b.load_const(None, Const::Int(2));
        let nlt2 = b.bin(
            None,
            BinOp::Lt,
            Operand::Slot(n),
            Operand::Slot(two),
            MirType::Bool,
        );
        // ids are sequential: the next two new_block() calls create 1 and 2
        b.br(Operand::Slot(nlt2), 1, 2);
        b.new_block(); // closes block 0 with the Br; now building block 1

        // block 1 (base): ret n
        b.ret(Some(Operand::Slot(n)));

        b.new_block(); // closes block 1 with Ret; now building block 2

        // block 2: fib(n-1) + fib(n-2)
        let one = b.load_const(None, Const::Int(1));
        let nm1 = b.bin(
            None,
            BinOp::Sub,
            Operand::Slot(n),
            Operand::Slot(one),
            MirType::Int,
        );
        let f1 = b
            .call(None, 0, vec![Operand::Slot(nm1)], MirType::Int)
            .expect("call dst");
        let nm2 = b.bin(
            None,
            BinOp::Sub,
            Operand::Slot(n),
            Operand::Slot(two),
            MirType::Int,
        );
        let f2 = b
            .call(None, 0, vec![Operand::Slot(nm2)], MirType::Int)
            .expect("call dst");
        let sum = b.bin(
            None,
            BinOp::Add,
            Operand::Slot(f1),
            Operand::Slot(f2),
            MirType::Int,
        );
        b.ret(Some(Operand::Slot(sum)));

        let fib = b.finish();
        let module = Module { fns: vec![fib] };
        let id = module.fn_by_name("fib").expect("fib present");
        (module, id)
    }

    fn native_fib(n: i64) -> i64 {
        if n < 2 {
            n
        } else {
            native_fib(n - 1) + native_fib(n - 2)
        }
    }

    #[test]
    fn recursive_fib_matches_native_reference() {
        let (m, entry) = fib_builder();
        for n in [0i64, 1, 2, 5, 10, 20] {
            let mut it = Interp::with_fuel(u64::MAX);
            let got = it
                .run(&m, entry, vec![Value::Int(n)])
                .unwrap_or_else(|e| panic!("fib({n}) failed: {e}"));
            assert_eq!(got, Value::Int(native_fib(n)), "fib({n}) parity");
        }
    }

    #[test]
    fn fib_runs_and_charges_fuel() {
        let (m, entry) = fib_builder();
        let mut it = Interp::with_fuel(u64::MAX);
        let got = it.run(&m, entry, vec![Value::Int(22)]).unwrap();
        assert_eq!(got, Value::Int(17_711));
        // fib(22) costs ~57k calls; the measured charge is ~287k ops, i.e.
        // ~5 charged MIR instructions per call (portable unit: one op per
        // MIR instruction).
        assert!(it.charged() > 250_000, "charge {}", it.charged());
    }

    #[test]
    fn loop_sum_with_branches() {
        // fn sum_to(n: Int) -> Int { let acc = 0; let i = 1;
        //   loop { if i <= n { acc += i; i += 1 } else { return acc } } }
        let mut b = FnBuilder::new(
            "sum_to",
            FnSig {
                params: vec![MirType::Int],
                ret: MirType::Int,
            },
        );
        let n = b.param(0);
        let acc = b.load_const(None, Const::Int(0));
        let one = b.load_const(None, Const::Int(1));
        let i = b.load_const(None, Const::Int(1));
        b.jmp(1); // block 0 falls into the loop head (block 1)
        let head = b.new_block(); // closes block 0 with Jmp; building block 1
        let le = b.bin(
            None,
            BinOp::Le,
            Operand::Slot(i),
            Operand::Slot(n),
            MirType::Bool,
        );
        b.br(Operand::Slot(le), 2, 3); // body = 2, done = 3
        b.new_block(); // closes block 1 with Br; building block 2

        // body: acc = acc + i; i = i + 1; jmp head
        let acc2 = b.bin(
            None,
            BinOp::Add,
            Operand::Slot(acc),
            Operand::Slot(i),
            MirType::Int,
        );
        b.copy(acc, acc2);
        let i2 = b.bin(
            None,
            BinOp::Add,
            Operand::Slot(i),
            Operand::Slot(one),
            MirType::Int,
        );
        b.copy(i, i2);
        b.jmp(head); // head is block 1

        b.new_block(); // closes block 2 with Jmp; building block 3
        b.ret(Some(Operand::Slot(acc)));

        let m = Module {
            fns: vec![b.finish()],
        };
        let entry = m.fn_by_name("sum_to").unwrap();
        let mut it = Interp::with_fuel(u64::MAX);
        let got = it.run(&m, entry, vec![Value::Int(100)]).unwrap();
        assert_eq!(got, Value::Int(5_050));
    }

    #[test]
    fn checked_overflow_traps_wrapping_wraps_identically() {
        // fn boom() -> Int { i64::MAX + 1 }  (checked)  vs (AddWrap) wrap
        let mut checked = FnBuilder::new(
            "boom",
            FnSig {
                params: vec![],
                ret: MirType::Int,
            },
        );
        let a = checked.load_const(None, Const::Int(i64::MAX));
        let one = checked.load_const(None, Const::Int(1));
        let s = checked.bin(
            None,
            BinOp::Add,
            Operand::Slot(a),
            Operand::Slot(one),
            MirType::Int,
        );
        checked.ret(Some(Operand::Slot(s)));
        let m_checked = Module {
            fns: vec![checked.finish()],
        };

        let mut wrapping = FnBuilder::new(
            "boomw",
            FnSig {
                params: vec![],
                ret: MirType::Int,
            },
        );
        let a = wrapping.load_const(None, Const::Int(i64::MAX));
        let one = wrapping.load_const(None, Const::Int(1));
        let s = wrapping.bin(
            None,
            BinOp::AddWrap,
            Operand::Slot(a),
            Operand::Slot(one),
            MirType::Int,
        );
        wrapping.ret(Some(Operand::Slot(s)));
        let m_wrap = Module {
            fns: vec![wrapping.finish()],
        };

        let ec = m_checked.fn_by_name("boom").unwrap();
        let ew = m_wrap.fn_by_name("boomw").unwrap();
        let mut it = Interp::with_fuel(u64::MAX);
        let err = it.run(&m_checked, ec, vec![]).unwrap_err();
        assert_eq!(err, MirError::Overflow { op: BinOp::Add });
        let mut it2 = Interp::with_fuel(u64::MAX);
        let got = it2.run(&m_wrap, ew, vec![]).unwrap();
        assert_eq!(got, Value::Int(i64::MIN));
        // the tier-consistency contract: same operands, different ops,
        // both semantics fixed in the IR so every backend agrees.
    }

    #[test]
    fn fuel_budget_is_charged_and_enforced() {
        let (m, entry) = fib_builder();
        let mut it = Interp::with_fuel(100);
        let err = it.run(&m, entry, vec![Value::Int(10)]).unwrap_err();
        assert!(matches!(err, MirError::OutOfFuel { .. }), "{err}");
        assert!(it.charged() <= 101);
    }

    #[test]
    fn call_depth_cap_is_portable() {
        // fn inf(n) -> Unit { inf(n) } — infinite recursion trips the cap.
        let mut b = FnBuilder::new(
            "inf",
            FnSig {
                params: vec![MirType::Int],
                ret: MirType::Unit,
            },
        );
        let n = b.param(0);
        b.call(None, 0, vec![Operand::Slot(n)], MirType::Unit);
        b.ret(None);
        let m = Module {
            fns: vec![b.finish()],
        };
        let entry = m.fn_by_name("inf").unwrap();
        let mut it = Interp::with_fuel(u64::MAX);
        let err = it.run(&m, entry, vec![Value::Int(1)]).unwrap_err();
        assert!(matches!(err, MirError::StackOverflow { .. }), "{err}");
    }

    #[test]
    fn validator_rejects_bad_modules() {
        // Int condition on Br: a typed-MIR rejection.
        let mut b = FnBuilder::new(
            "bad",
            FnSig {
                params: vec![],
                ret: MirType::Unit,
            },
        );
        let z = b.load_const(None, Const::Int(0));
        b.br(Operand::Slot(z), 1, 2); // Int condition: a typed-MIR rejection
        b.new_block(); // closes block 0 with the bad Br; building block 1
        b.ret(None);
        b.new_block(); // closes block 1 with Ret; building block 2
        b.ret(None);
        let m = Module {
            fns: vec![b.finish()],
        };
        let err = m.validate().unwrap_err();
        assert!(
            err.to_string().contains("br condition is not Bool"),
            "{err}"
        );

        // arity mismatch on Call
        let (m2, _) = fib_builder();
        let mut b2 = FnBuilder::new(
            "caller",
            FnSig {
                params: vec![],
                ret: MirType::Int,
            },
        );
        let callee = m2.fn_by_name("fib").unwrap();
        let r = b2.call(None, callee, vec![], MirType::Int);
        b2.ret(Some(Operand::Slot(r.unwrap())));
        let m3 = Module {
            fns: vec![m2.fns[0].clone(), b2.finish()],
        };
        let err = m3.validate().unwrap_err();
        assert!(err.to_string().contains("wants 1 args, got 0"), "{err}");
    }

    #[test]
    fn float_math_is_deterministic_binary64() {
        // fn kernel(x: Float) -> Float { x * 3.0 + 1.5 }
        let mut b = FnBuilder::new(
            "kernel",
            FnSig {
                params: vec![MirType::Float],
                ret: MirType::Float,
            },
        );
        let x = b.param(0);
        let c1 = b.load_const(None, Const::Float(3.0));
        let c2 = b.load_const(None, Const::Float(1.5));
        let m = b.bin(
            None,
            BinOp::Mul,
            Operand::Slot(x),
            Operand::Slot(c1),
            MirType::Float,
        );
        let a = b.bin(
            None,
            BinOp::Add,
            Operand::Slot(m),
            Operand::Slot(c2),
            MirType::Float,
        );
        b.ret(Some(Operand::Slot(a)));
        let modl = Module {
            fns: vec![b.finish()],
        };
        let entry = modl.fn_by_name("kernel").unwrap();
        let mut it = Interp::with_fuel(u64::MAX);
        let got = it.run(&modl, entry, vec![Value::Float(2.5)]).unwrap();
        let native = 2.5_f64 * 3.0 + 1.5;
        assert_eq!(got, Value::Float(native));
        // bit-for-bit determinism: the same module must produce the same
        // bits on every run (a standing determinism pin, brief §8.14/§22).
        let mut it2 = Interp::with_fuel(u64::MAX);
        let got2 = it2.run(&modl, entry, vec![Value::Float(2.5)]).unwrap();
        assert_eq!(std::mem::discriminant(&got), std::mem::discriminant(&got2));
        if let (Value::Float(a), Value::Float(bb)) = (&got, &got2) {
            assert_eq!(a.to_bits(), bb.to_bits());
        }
    }

    #[test]
    fn arg_type_mismatch_is_an_error() {
        let (m, entry) = fib_builder();
        let mut it = Interp::with_fuel(u64::MAX);
        let err = it
            .run(&m, entry, vec![Value::Str("nope".into())])
            .unwrap_err();
        assert!(matches!(err, MirError::ArgMismatch { .. }), "{err}");
    }
}
