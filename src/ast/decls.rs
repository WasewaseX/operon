//! ast/decls.rs, the declaration-borne AST nodes: genes, phenotypes,
//! traits, splices, regulation edges and the type-annotation grammar.
//! Split out of ast.rs by responsibility; every name is re-exported from
//! the ast root so `crate::ast::*` paths are unchanged.

use std::sync::Arc;

use super::Expr;
use super::stmts::Stmt;

#[derive(Debug, Clone, Default)]
pub struct GeneDef {
    pub name: Option<String>,
    /// A13 (dx-r2): source line of the definition, runtime gate notes
    /// (grn veto, methylation silencing, etc.) render real locations.
    pub line: usize,
    /// W074: `##` doc-comment lines attached to this declaration (metadata
    /// only, never evaluated, mirrored by fmt/hover/`operon doc`).
    pub doc: Vec<String>,
    pub params: Vec<(String, Option<Expr>)>,
    pub guard: Option<(Expr, Vec<Stmt>)>,
    pub body: Vec<Stmt>,
    pub acetylate: bool,
    pub methylate: bool,
    pub m6a: bool,
    /// reg-bio-3 (C10): gene dosage, `@copies n`. Copies amplify the
    /// concentration the gene feeds its GRN edges (transcript amount),
    /// NOT the call's return value. Clamped 1..=64 at parse.
    pub copies: u32,
    pub seq: bool, // sequence (generator) definition
    /// loop-9 (F-5): a CIS riboswitch aptamer in this transcript's own 5'UTR
    ///, `(ligand, bound_means_on, threshold)`. The metabolite pool is
    /// cell-wide; the SENSOR is per-gene. `off` class (TPP/purine/SAM):
    /// bound -> terminator hairpin -> OFF. `on` class (adenine/glycine
    /// activators): bound -> RBS exposed -> ON.
    pub riboswitch: Option<(String, bool, f64)>,
    /// loop-9 (F-2): per-gene PROMOTER IDENTITY, `@burst kon koff`. The
    /// telegraph layer's rates for THIS gene (overrides the global
    /// expr_on/.cell rates). Burst size ~ k_tx/k_off, burst frequency ~
    /// k_on: different promoters have different (kon, koff), that is
    /// their identity. Rides the gene Arc, so workers inherit for free.
    pub burst: Option<(f64, f64)>,
    /// W01 (L2c): soft type annotations, parallel to `params` (same
    /// length; None where unannotated). Enforced at the call funnel as
    /// catchable `unfolded` Stress (SPEC §7a); never a parse rejection.
    pub param_anns: Vec<Option<TypeAnn>>,
    /// W01: return annotation, `gene f() -> int { }`. Checked when the
    /// gene produces its return value (including a `?!`-propagated one).
    pub ret_ann: Option<TypeAnn>,
    /// W64: `@deprecated("migration text", since="2.4")` metadata. Parse
    /// and tooling surface only (lint `deprecated-use` findings, doc/fmt
    /// round-trip); the interpreter never reads it, runtime is untouched.
    pub deprecated: Option<Deprecation>,
    /// TYPED-MODE: declared generic type parameters, `gene first<T>(...)`.
    /// (name, optional bound) — the bound is a trait/constraint name. Pure
    /// metadata for the static checker and fmt/doc round-trip; the dynamic
    /// evaluator never reads it.
    pub type_params: Vec<(String, Option<String>)>,
}

/// W64: the structured payload of a deprecation mark.
#[derive(Debug, Clone, Default)]
pub struct Deprecation {
    /// The migration text: what to use instead, why the mark exists.
    pub message: String,
    /// Optional calendar gate from the compatibility ladder (W63),
    /// `since="2.4"`: the release that started the deprecation clock.
    pub since: Option<String>,
}

/// W01 (L2c): the annotation grammar, `int`, `float`, `str`, `bool`,
/// `list`, `map`, `gene`, `sequence`, `phenotype`, `any`, unions (`int |
/// str`), optionals (`int?`). Matching is by `Value::type_name()` with
/// documented numeric widening (`float` accepts int; `int` refuses float)
/// and `any` accepting everything. This is a SOFT contract: violations are
/// recoverable Stress, never parse rejections.
#[derive(Debug, Clone)]
pub enum TypeAnn {
    Named(String),
    Union(Vec<TypeAnn>),
    Optional(Box<TypeAnn>),
    /// TYPED-MODE: generic annotation, `list[int]`, `map[str, int]`,
    /// `result[int, str]`, `option[t]`. The name is the head; the args are
    /// the bracketed parameters. Runtime soft matching treats a generic
    /// annotation's HEAD like the bare name (list[int] enforces "is a
    /// list") — element types are the static checker's business.
    Generic(String, Vec<TypeAnn>),
    /// W01-s2 type aliases: an annotation naming a declared alias
    /// (`type Metrics = map[str, float]`, then `m: Metrics`). The parser
    /// resolves the name at parse time; matching is the TARGET's law
    /// (runtime + checker both recurse into `target`). No forward
    /// references: an annotation naming an alias BEFORE its declaration
    /// stays a plain `Named` and the typo-armor rule applies.
    Alias {
        name: String,
        target: Box<TypeAnn>,
    },
}

impl TypeAnn {
    /// Canonical rendering (messages, fmt roundtrip, hover). Must match the
    /// oracle's ann_render op-for-op.
    pub fn render(&self) -> String {
        match self {
            TypeAnn::Named(n) => n.clone(),
            TypeAnn::Union(alts) => alts
                .iter()
                .map(|a| a.render())
                .collect::<Vec<_>>()
                .join(" | "),
            TypeAnn::Optional(inner) => format!("{}?", inner.render()),
            TypeAnn::Generic(name, args) => format!(
                "{}[{}]",
                name,
                args.iter()
                    .map(|a| a.render())
                    .collect::<Vec<_>>()
                    .join(", ")
            ),
            TypeAnn::Alias { name, .. } => name.clone(),
        }
    }
}

#[derive(Debug, Clone)]
pub struct PhenoDef {
    pub name: String,
    /// A13: source line of the definition (dx-r2 spans).
    pub line: usize,
    /// W074: doc-comment lines (metadata only).
    pub doc: Vec<String>,
    pub parent: Option<String>,
    /// W04: implemented traits, in declaration order (`implements A, B`).
    /// Method dispatch falls back to trait DEFAULT methods in this order
    /// after the phenotype's own lineage misses.
    pub implements: Vec<String>,
    pub fields: Vec<(String, Expr)>, // field name -> default expr
    pub methods: Vec<Arc<GeneDef>>,
}

/// W04 (SPEC §8b): a trait declaration, a named set of method contracts.
/// A method without a body is REQUIRED (the implementing phenotype must
/// provide it; construction notes a contract break, calls wobble); a
/// method with a body is a DEFAULT (used when the phenotype lineage has
/// no method of that name).
#[derive(Debug, Clone)]
pub struct TraitMethod {
    pub name: String,
    pub line: usize,
    pub required: bool,
    /// Full gene definition (params + body) parsed by the normal gene
    /// parser, default methods are ordinary genes with a `self` binding.
    pub default: Option<Arc<GeneDef>>,
}
#[derive(Clone)]
pub struct TraitDef {
    pub name: String,
    pub line: usize,
    pub doc: Vec<String>,
    pub methods: Vec<TraitMethod>,
}
impl std::fmt::Debug for TraitDef {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("TraitDef")
            .field("name", &self.name)
            .field(
                "methods",
                &self.methods.iter().map(|m| &m.name).collect::<Vec<_>>(),
            )
            .finish()
    }
}

#[derive(Debug, Clone)]
pub struct SpliceDef {
    pub root: String,
    /// A13: source line of the definition (dx-r2 spans).
    pub line: usize,
    /// W074: doc-comment lines (metadata only).
    pub doc: Vec<String>,
    pub variants: Vec<(String, Arc<GeneDef>)>, // (variant name, gene)
}

/// reg-bio (F-5): inline ring kinetics, `repressilator a -> b -> c alpha 20;`.
/// Each field layers onto the interpreter's current `RepressiParams` (last
/// declaration wins per-field); None leaves the value untouched, so `.cell`
/// configuration and inline overrides compose.
#[derive(Debug, Clone, Default)]
pub struct RepressiOverrides {
    pub alpha: Option<f64>,
    pub gamma: Option<f64>,
    pub hill: Option<u32>,
    pub basal: Option<f64>,
    pub noise: Option<f64>,
    pub seed: Option<u64>,
}

#[derive(Debug, Clone)]
pub struct FateDef {
    pub name: String,
    /// A13: source line of the definition (dx-r2 spans).
    pub line: usize,
    /// W074: doc-comment lines (metadata only).
    pub doc: Vec<String>,
    pub states: Vec<(String, Vec<String>)>, // state -> allowed targets
    pub enter: Option<String>,
}

#[derive(Debug, Clone)]
pub struct RegEdge {
    pub from: String,
    pub to: String,
    pub strength: f64,
    pub inhibit: bool,
    pub threshold: Option<f64>, // Hill-style dose threshold
    /// reg-bio (F-2): per-edge Hill exponent (1..=8). None = the historical
    /// n=2 dose-response (bit-identical legacy path). Only meaningful on
    /// edges carrying a threshold (dose-response shape).
    pub hill: Option<u32>,
    /// reg-bio (F-3): cis-regulatory OR membership. An `any` edge passes the
    /// call gate when its own threshold passes, the gene fires if ALL
    /// non-any thresholded edges pass AND at least one `any` edge passes.
    /// Inhibiting edges ignore `any` (inhibitors already veto with OR
    /// semantics: any inhibitor above its threshold vetoes).
    pub any: bool,
    /// reg-bio-2 (D2b): occupancy repression. An inhibiting edge marked
    /// `occupy` composes multiplicatively, child *= 1 − influence, the
    /// thermodynamic Kⁿ/(Kⁿ+Rⁿ) survival form where repression can never
    /// overshoot and full occupancy means full silencing. Legacy edges
    /// subtract once (bit-identical default).
    pub occupy: bool,
    /// reg-bio-2 (B7): synergistic pooling. `sum` activating (thresholded)
    /// edges targeting the same gene pool their weighted inputs,
    /// P = min(1, Σ strength·level), and ONE Hill function of P drives
    /// both the gate and the fire influence, so two sub-threshold inputs
    /// can fire together (enhanceosome synergy). Edge groups are keyed by
    /// (target, threshold, hill); edges without `sum` are untouched.
    pub sum: bool,
    /// reg-bio-2 (A5/C7): an `attenuates` edge vetoes like an inhibitor but
    /// reports the RNA-level mechanism, transcription attenuation (leader
    /// peptide / terminator hairpin outcome), not TF occlusion.
    pub attenuates: bool,
}

/// reg-bio-2 (A4): an allosteric binding record, `bind tf inducer lig k v;`
/// or `bind tf cofactor lig k v;`. Ligand binding modulates the regulator's
/// DNA-available fraction: an INDUCER reduces affinity (allolactose on LacI
///, binding relieves repression), a COFACTOR increases it (tryptophan on
/// TrpR, binding enables repression). At every regulation read of `tf`:
///   occ = L / (k + L)
///   free = level × Π(1 − occ) over inducers × Π occ over cofactors
#[derive(Debug, Clone)]
pub struct BindDef {
    pub tf: String,
    pub ligand: String,
    /// "inducer" reduces DNA affinity; "cofactor" increases it
    pub inducer: bool,
    /// dissociation-style constant (occ = L/(k+L)); default 0.1
    pub k: f64,
}

/// reg-bio-2 (C1): the translation layer. A `translates` edge models
/// mRNA→protein production: at every engine update point (a `grn_fire`
/// pulse, a decay-clock tick) the target protein node integrates one Euler
/// step of the classic two-tier ODE
///     p ← p + rate·Δcalls − decay·p      (clamped 0..1)
/// where Δcalls is the source gene's call-count delta since the last
/// integration, transcripts accumulate in the call counters, protein
/// accumulates here, lagging and smoothing the transcriptional bursts.
/// Protein nodes live in `grn_levels`, so any GRN gate can read a protein
/// as its regulator (two-tier regulation).
#[derive(Debug, Clone)]
pub struct TransEdge {
    pub from: String,
    pub to: String,
    /// translation rate per transcript call (default 1.0)
    pub rate: Option<f64>,
    /// protein decay fraction per integration (default 0.0, stable product)
    pub decay: Option<f64>,
}
