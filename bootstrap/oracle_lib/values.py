"""operon oracle: values (split of bootstrap/oracle.py)."""

import contextlib
import sys
import math
from .fmt import v_display, v_repr
from .mapops import _map_items



# compat-r3 (environment-pair repair, F-assigned per digest-4, 2026-10-04;
# C veto-at-review): normalize this process's stdout/stderr to UTF-8 with
# LF-only newlines on EVERY platform. Windows runners run text mode in the
# platform locale (cp1252): non-cp1252 output raised UnicodeEncodeError, and
# text-mode writes translated \n to \r\n — the Rust core emits byte-exact
# UTF-8/LF, so either mechanism alone makes every comparison against the
# oracle diverge (the 100%-uniform phantom class: 0/3504 with zero real
# semantic deltas). Same lesson as harness.py's W59/compat-r2 fixes, applied
# at the oracle itself so EVERY invocation path inherits it (compat_matrix.sh,
# ci.yml's differential step, test.sh, cookbook.sh, run_diff_shard.py,
# bench_compare.py). No-op on Linux/macOS defaults.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        # best-effort console setup: a non-reconfigurable stream is fine as-is
        with contextlib.suppress(ValueError, OSError):
            _stream.reconfigure(encoding="utf-8", errors="replace", newline="\n")

class Note:
    __slots__ = ("rung", "line", "message")
    def __init__(self, rung, message, line=0):
        # compat matrix fix: the Rust core stores the origin line on every
        # note (ast.rs Note{line, rung, message}) and tools::flush_notes
        # renders `[tag] file:line: msg`. The oracle now mirrors both.
        self.rung, self.line, self.message = rung, line, message

# W101 slice 7 mirror of diag.rs::note_code (SPEC 9a.1): the derived E2xxx
# code rides the tag in flush output (`[fallback E2012] ...`). Ordered
# substring families, specific first, generic last; new families APPEND and
# codes never renumber. A message matching nothing renders uncoded, exactly
# like the Rust side. corpus-r3: this mirror was missing after 14888da and
# every parse-repair note diverged from the engines in the compat matrix.
def note_code(message):
    if "note cap" in message:
        return "E2000"
    if "single-quoted string repaired" in message:
        return "E2001"
    if "single-quoted bytes literal repaired" in message:
        return "E2002"
    if "malformed \\x escape" in message:
        return "E2003"
    if "non-ASCII char in bytes literal" in message:
        return "E2004"
    if "unclosed bytes literal" in message:
        return "E2005"
    if "unclosed multiline string" in message or "unclosed raw string" in message:
        return "E2006"
    if "stray '@' skipped" in message:
        return "E2007"
    if "out of range treated as 0" in message:
        return "E2008"
    if "malformed number" in message:
        return "E2009"
    if message.startswith("synonym "):
        return "E2010"
    if message.startswith("wobble: "):
        return "E2011"
    if "unmatched '}' skipped" in message:
        return "E2012"
    if "auto-closed" in message:
        return "E2013"
    if "unknown mark '@" in message:
        return "E2018"
    if "binds null" in message:
        return "E2015"
    if "needs " in message or "missing 'in'" in message:
        return "E2016"
    if "treated as" in message:
        return "E2017"
    if "null substituted" in message:
        return "E2019"
    if "skipped" in message:
        return "E2014"
    if message.startswith("phantom call to "):
        return "E2030"
    return ""

class Stress(Exception):
    def __init__(self, kind, message):
        self.kind, self.message = kind, message
        # W007 mirror: gene call chain captured during unwinding, innermost
        # frame first, (gene, call-site line); capture cap 64 matches Rust.
        self.chain = []
        # W06 (D-014) mirror: propagation marker, Some payload means this is
        # NOT a failure but a `?!` signal unwinding to the gene boundary.
        # No user path constructs a Stress with a payload (raise/stress go
        # through the kind/message constructor), so rescue can never catch
        # or spoof propagation. Every catch site pre-arms on `prop`.
        self.prop = None
    def as_map(self):
        # W07 mirror: rescue binding carries the chain, same field order as
        # the Rust stress_map (kind, message, chain). Stress.line stays a
        # Rust-side stderr-rendering field (dx-r3), not mirrored here.
        return {"kind": self.kind, "message": self.message,
                "chain": [{"gene": n, "line": l} for (n, l) in self.chain]}

class Variant:
    """W06 (D-014) mirror: first-class Option/Result variant value.
    tag is one of {Some, None, Ok, Err}; payload is None for None and a
    value otherwise. Families are distinct: Some(x) != Ok(x), the tag IS
    the contract."""
    __slots__ = ("tag", "payload")
    def __init__(self, tag, payload):
        self.tag, self.payload = tag, payload
    def __repr__(self):
        return v_repr(self)

class Gene:
    __slots__ = ("name", "params", "guard", "body", "acetylate", "methylate", "m6a", "copies", "seq", "riboswitch", "burst", "closure", "param_anns", "ret_ann", "type_params", "line")
    def __init__(self, name, params, guard, body, ac=False, me=False, m6=False, copies=1, seq=False, riboswitch=None, burst=None, param_anns=None, ret_ann=None, type_params=None, line=0):
        self.name, self.params, self.guard, self.body = name, params, guard, body
        self.acetylate, self.methylate, self.m6a, self.copies, self.seq = ac, me, m6, copies, seq
        # loop-9 (F-5): cis riboswitch (ligand, bound_means_on, threshold)
        self.riboswitch = riboswitch
        # loop-9 (F-2): per-gene promoter identity (kon, koff)
        self.burst = burst
        # W01 (L2c): soft type annotations (mirror of GeneDef.param_anns/ret_ann)
        self.param_anns = param_anns if param_anns is not None else []
        self.ret_ann = ret_ann
        # TYPED-MODE: declared generic type parameters (mirror of GeneDef.type_params)
        self.type_params = type_params if type_params is not None else []
        # Z-CAPWINDOW (L-053): the def keyword's line (A13/dx-r2 mirror of
        # GeneDef.line) — the call-repair notes (missing/extra argument)
        # stamp it LOCATED exactly like the engine.
        self.line = line
        self.closure = None

ENHANCE_DELTA = 0.25  # T2e: super-enhancer activation boost (GRN threshold reduction)
M64 = 0xFFFFFFFFFFFFFFFF

# reg-bio (F-5): default ring kinetics, the historical constants.
DEFAULT_REPRESSI = {"alpha": 10.0, "gamma": 1.0, "hill": 4, "basal": 0.0, "noise": 0.0,
                    "seed": 0x9E3779B97F4A7C15}

def repressilator_levels(n, tick, params=None):
    """A11 (reg-r2) / reg-bio (F-5): mirror of the Rust `repressilator_levels_p`.

    Discrete Elowitz–Leibler ring: dA/dt = α/(1 + R^h) + basal − γA,
    Euler-integrated, 20 substeps of dt=0.05 per ring tick, init [5, 0, ...].
    Node j's repressor is node (j+n−1) mod n. With default params (noise off)
    this is bit-identical to the historical form. The optional noise kick is
    drawn per (tick, substep, node) from a stream derived from the ABSOLUTE
    position, the same derivation as the Rust core, so fold-from-init and
    incremental-cache paths agree bit-for-bit in BOTH implementations.
    """
    if n == 0:
        return []
    p = params if params is not None else DEFAULT_REPRESSI
    ALPHA, GAMMA, DT, SUB = p["alpha"], p["gamma"], 0.05, 20
    HILL, BASAL, NOISE, SEED = p["hill"], p["basal"], p["noise"], p["seed"]
    lv = [0.0] * n
    lv[0] = 5.0
    for t in range(tick):
        for ss in range(SUB):
            nx = 0
            if NOISE > 0.0:
                nx = (SEED ^ ((t * 0x9E3779B97F4A7C15) & M64)
                      ^ ((ss * 0xBF58476D1CE4E5B9) & M64)) & M64
                if nx == 0:
                    nx = 0x9E3779B97F4A7C15
            snap = lv[:]
            for j in range(n):
                rep = snap[(j + n - 1) % n]
                # rep^hill via repeated multiplication, op-identical to Rust
                # (default h=4 == the historical rep*rep*rep*rep exactly)
                rh = 1.0
                for _k in range(HILL):
                    rh *= rep
                d = ALPHA / (1.0 + rh) + BASAL - GAMMA * snap[j]
                v = snap[j] + DT * d
                if NOISE > 0.0:
                    nx ^= (nx >> 12) & M64
                    nx ^= (nx << 25) & M64
                    nx ^= (nx >> 27) & M64
                    nx &= M64
                    u = ((nx >> 11) & ((1 << 53) - 1)) / 9007199254740992.0
                    # reg-bio-2 (D6): multiplicative, dt-aware noise, op-for-op
                    # mirror of the Rust core. The constant is the literal double
                    # nearest 1/√20 on BOTH sides (no math.sqrt call, the value
                    # is fixed text, so IEEE parity is trivial).
                    v = v * (1.0 + NOISE * 0.22360679774997896 * (2.0 * u - 1.0))
                lv[j] = v if v > 0.0 else 0.0
    return lv

def grapheme_count(s):
    """W28 (SPEC 3): grapheme-cluster count over a DOCUMENTED SUBSET of the
    extended-grapheme rules (mirror of the Rust core's grapheme_count):
    base + combining marks (U+0300-036F, U+1AB0-1AFF, U+1DC0-1DFF,
    U+20D0-20FF, U+FE20-FE2F), ZWJ (U+200D) glues prev+next, regional-
    indicator pairs (flags) are one cluster each."""
    chars = list(s)
    combining = lambda cp: (0x0300 <= cp <= 0x036F or 0x1AB0 <= cp <= 0x1AFF or
                            0x1DC0 <= cp <= 0x1DFF or 0x20D0 <= cp <= 0x20FF or
                            0xFE20 <= cp <= 0xFE2F)
    ri = lambda cp: 0x1F1E6 <= cp <= 0x1F1FF
    n = len(chars)
    clusters = 0
    i = 0
    while i < n:
        clusters += 1
        cp = ord(chars[i])
        if ri(cp):
            if i + 1 < n and ri(ord(chars[i + 1])):
                i += 2
            else:
                i += 1
            continue
        j = i + 1
        zwj_forward = cp == 0x200D
        while j < n:
            c2 = ord(chars[j])
            if combining(c2):
                j += 1
            elif c2 == 0x200D:
                j += 1
                zwj_forward = True
            elif zwj_forward:
                j += 1
                zwj_forward = False
            else:
                break
        i = j
    return clusters


class Pheno:
    __slots__ = ("name", "parent", "fields", "methods", "implements")
    def __init__(self, name, parent, fields, methods, implements=None):
        self.name, self.parent, self.fields, self.methods = name, parent, fields, methods
        # W04: implemented traits, in declaration order (SPEC 8b)
        self.implements = implements or []

class TraitM:
    """W04: one trait method contract. required=True means the implementing
    phenotype must provide it; default is the full GeneDef body otherwise."""
    __slots__ = ("name", "required", "default")
    def __init__(self, name, required, default):
        self.name, self.required, self.default = name, required, default

class Trait:
    __slots__ = ("name", "methods")
    def __init__(self, name, methods):
        self.name, self.methods = name, methods

class ObjInst:
    __slots__ = ("defn", "fields")
    def __init__(self, defn, fields):
        self.defn, self.fields = defn, fields

class Channel:
    """W015 mirror: unbounded FIFO channel, created empty. The sequential
    oracle never blocks (the differential corpus writes buffered sends
    before recvs/selects), so the buffer is a plain list of WIRE-form
    payloads: the Rust queue stores SendValue, and channel_wire below is
    its sequential mirror, applied at send time on both cores so the
    membrane contract is one rule on the same-thread buffered path too."""
    __slots__ = ("buf", "closed")
    def __init__(self):
        self.buf = []
        self.closed = False

class WeakRef:
    """W013 (D-013) mirror: opaque weak handle (the weak() builtin). Holds a
    weakref to the target's backing store, it does NOT keep the value alive;
    strengthen() returns null once the last strong reference is gone (the
    Rust core frees at strong-count zero, no GC). Phenotype handles carry
    the shared per-class definition so strengthen can rebuild the SAME
    instance (same fields dict) while the instance is alive; holding the
    definition never keeps an instance alive. addr is the target address at
    handle creation, the identity rule for deep_eq (same as the Rust
    same_target: same backing-store allocation)."""
    __slots__ = ("kind", "addr", "defn")
    def __init__(self, kind, addr, defn=None):
        # no Python weakref here: plain list/dict are not weakref-able, and
        # the oracle models the RULES deterministically instead. The target
        # is registered strongly on the interpreter (self.weak_targets); the
        # ALIVE question is answered by an env-chain identity scan at
        # strengthen() time (a binding somewhere on the live scope chain
        # holds the target = a strong reference exists). Same-thread,
        # sequential: matches the Rust Rc semantics on every pin-able shape.
        self.kind, self.addr, self.defn = kind, addr, defn

def channel_wire(v, _d=0):
    """W015 mirror of the Rust channel wire serialization (genes.to_send_d):
    map keys stringify through display, nested behavior handles (genes,
    sequences, channels) degrade to null, nested phenotype instances become
    maps carrying the hidden #phenotype key, variants ride with their
    payload. Top-level handles never reach this function (send refuses them
    with a catchable `membrane` stress first)."""
    if _d > 100_000:
        return None
    if v is None or isinstance(v, (bool, int, float, str, bytes)):
        return v
    if isinstance(v, list):
        return [channel_wire(x, _d + 1) for x in v]
    if isinstance(v, dict):
        # #214 + Z-MAPORDER: the WIRE is the unified insertion sequence —
        # one walk over _map_items (the Rust SendValue::Map k.display()
        # contract); the old {**dict, **side} merge ordered dict-entries
        # first even when a container key was inserted before a scalar one
        return {(k if isinstance(k, str) else v_display(k)): channel_wire(x, _d + 1)
                for k, x in _map_items(v)}
    if isinstance(v, Variant):
        return Variant(v.tag, None if v.payload is None else channel_wire(v.payload, _d + 1))
    if isinstance(v, ObjInst):
        out = {"#phenotype": v.defn.name}
        for k, x in v.fields.items():
            out[k] = channel_wire(x, _d + 1)
        return out
    # Gene / SeqObj / Channel handles degrade to null, like the spawn wire
    return None

def channel_degrade_result(v, _d=0):
    """W015 mirror of the Rust join-result path (genes.to_send_d): a channel
    handle degrades to null, deeply inside containers, and a propagated
    variant keeps its tag while its payload degrades. The wider result-path
    wire gaps (map-key stringification, phenotype-to-map) predate W015 and
    are corpus-avoided; this mirrors only the channel rule."""
    if isinstance(v, Channel):
        return None
    if _d > 100_000:
        return v
    if isinstance(v, list):
        return [channel_degrade_result(x, _d + 1) for x in v]
    if isinstance(v, dict):
        # Z-MAPORDER: unified insertion sequence (see channel_wire)
        return {(k if isinstance(k, str) else v_display(k)): channel_degrade_result(x, _d + 1)
                for k, x in _map_items(v)}
    if isinstance(v, Variant):
        return Variant(v.tag, None if v.payload is None
                       else channel_degrade_result(v.payload, _d + 1))
    return v

class SeqObj:
    """Sequential-oracle sequence: values are produced by running the body to
    completion on first pull (buffered), then served one at a time. The Rust
    core pulls lazily via a rendezvous worker; corpus-visible output is
    identical because the differential programs do not print inside bodies."""
    __slots__ = ("interp", "gene", "args", "buf", "idx", "done")
    def __init__(self, interp, gene, args):
        self.interp, self.gene, self.args = interp, gene, args
        self.buf = None
        self.idx = 0
        self.done = False

    def pull(self):
        if self.buf is None:
            self.buf = []
            saved = self.interp.seq_buffer
            self.interp.seq_buffer = self.buf
            try:
                g = self.gene
                fenv = self.interp.new_scope(g.closure if g.closure is not None else self.interp.globals)
                for i, (pname, dflt) in enumerate(g.params):
                    if pname in ("?", ""):
                        continue
                    if i < len(self.args):
                        fenv[pname] = self.args[i]
                    elif dflt is not None:
                        fenv[pname] = self.interp.eval_expr(fenv, dflt)
                    else:
                        fenv[pname] = None
                try:
                    with contextlib.suppress(Return):
                        self.interp.exec_block(fenv, g.body)
                except Stress as st:
                    # W06 (D-014) mirror: propagation inside a sequence ends
                    # the stream, sequences are streams, not answers, so the
                    # variant has no return path; the stream ends cleanly
                    # (never leaked as a kind). Matches genes.rs run_seq_body.
                    if st.prop is not None:
                        self.interp.note(4, "propagation ended the sequence")
                    else:
                        raise
            finally:
                self.interp.seq_buffer = saved
        if self.idx < len(self.buf):
            v = self.buf[self.idx]
            self.idx += 1
            return v
        return None

class Return(Exception):
    def __init__(self, value):
        self.value = value

class BreakLoop(Exception):
    pass

class ContinueLoop(Exception):
    pass
