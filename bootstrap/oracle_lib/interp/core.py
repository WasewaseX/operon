"""operon oracle: interp.core (split of bootstrap/oracle.py)."""

import os
from ..mapops import _map_items_side
from ..values import DEFAULT_REPRESSI, Note, Stress



class ICore:
    def __init__(self, cell=None, cli_args=None):
        self.notes = []
        # Z-CAPWINDOW (L-053) mirror of Interp::note notes_dropped: counts
        # eval notes suppressed past the 10k cap (gates the one boundary note).
        self.notes_dropped = 0
        self.cell = cell or {}
        # W05: frozen-container registry (id() of lists/dicts bound via const).
        # Frozen-ness does NOT cross the spawn boundary: the reachable ids are
        # parked for the duration of an inline spawn body (mirror of the Rust
        # per-worker fresh containers, SPEC §7d).
        # W05 hardening (rt_p18a): frozen_keep HOLDS the registered containers
        # so their id()s can never be recycled by a fresh allocation while the
        # interpreter lives (CPython id-reuse would falsely freeze an innocent
        # new list after a gene-local const is collected).
        self.frozen_ids = set()
        self.frozen_keep = []
        # W013 (D-013) mirror: live DETECTED-cycle registry. Entries are
        # (weakref, addr) pairs; a registration is added when an insertion
        # closes a cycle (see _cycle_note_list/_cycle_note_map below) and
        # dies when the container is reclaimed (weakref dead) or the cycle
        # edge was broken by mutation (the lazy re-verify in _live_cycles).
        # Weakrefs only: accounting never extends a value's lifetime.
        self.cycle_regs = []
        self.weak_targets = {}  # W013: addr -> (kind, strong target, defn)
        # W069: importing-entry directory, candidate root #1 for `use`
        # (SPEC §8 resolution table). None until load_file sets it.
        self.base_dir = None
        # W19/W23 mirror: vendored dependency roots from operon.lock
        # (package name -> cache dir), consulted as resolution root 7.
        self.lock_dirs = []
        self.silences = []
        # reg-bio-3: operons / stoichiometric-RISC bookkeeping / m6A levels /
        # generation counter / gene dosage registry (mirror of the Rust core)
        self.operons = []
        # loop-10 (F-7/F-8): Rho/queue state, rho_pins is the worker-side
        # resolved knob tuple (None on the host: .cell resolved per use,
        # mirror of the Rust rho_knobs); ribo_queue is the per-cistron
        # queue register (rho.termination-gated bookkeeping).
        self.rho_pins = None
        self.ribo_queue = {}
        self.risc_escaped = set()
        self.m6a_levels = {}
        self.generation = 0
        self.copies = {}
        self.fates = {}
        self.phenos = {}
        # W04: trait registry (name -> Trait); last declaration wins
        self.traits = {}
        self.grn_edges = []
        self.grn_levels = {}
        self.toggles = []
        self.repressi_ring = []
        self.repressi_i = 0
        self.repressi_tick = 0
        self.ires = []
        self.enhanced = []
        self.defined_genes = []
        self.call_counts = {}
        self.call_clock = 0
        self.gene_buckets = {}
        self.modules = {}
        self.loading = []
        self.globals = {"__parent__": None}
        self.cli_args = cli_args or []
        self.steps = 0
        self.depth = 0
        self.depth_limit = 10_000
        # W07 mirror: line of the call/binop/index expression currently
        # executing (A13/dx-r4 parity), feeds traceback chain frames.
        self.cur_line = 0
        self.methyl_quiet = False
        self.methyl_noted = set()
        # T2b graded methylation: per-gene silencing level (@methylate defs +1,
        # @acetylate defs -1). Calls are blocked at methyl_threshold (default 3).
        self.methyl_levels = {}
        self.methyl_threshold = 3
        self.asserts_run = 0
        self.rng = 0x9E3779B97F4A7C15
        # reg-bio (F-6): enhancer dose (default 0.25)
        self.enhance_delta = 0.25
        # reg-bio (F-1): telegraph promoter layer (opt-in via .cell)
        self.expr_stochastic = False
        self.expr_kon = 0.3
        self.expr_koff = 0.1
        # reg-bio-2 (C2): decay-clock runtime override (decay_clock builtin)
        self.decay_clock_n = None
        self.decay_clock_f = None
        self.promoter_states = {}
        self.burst_off = {}
        # reg-bio (F-5): repressilator kinetics (defaults = historical constants)
        self.repressi_params = dict(DEFAULT_REPRESSI)
        # reg-bio-2 (C1/C11): translation layer + decoy sites
        self.trans_edges = []
        self.trans_last = {}
        self.decoys = []
        # reg-bio-2 (A4): ligand pools + allosteric bindings
        self.ligands = []
        self.ligand_pools = {}
        # loop-9 (C8): quorum-sensing signal species + the shared medium
        # (species -> integer molecule count). The oracle is sequential, so
        # one dict IS the shared medium; inline spawn shares it naturally.
        self.signals = []
        self.medium = {}
        # loop-9 (F-4): runtime splice shifts (root -> variant name)
        self.splice_shift = {}
        self.splice_registry = {}
        # loop-9 (F-3): per-gene promoter attempt telemetry (mirror)
        self.promoter_tel = {}
        # loop-9 (R9): runtime promoter-rate modulation (mirror)
        self.burst_overrides = {}
        self.grn_binds = []
        self.seq_buffer = None
        self.caps = {"enabled": True, "read": [], "write": [], "run": [], "net": [], "env": [], "py": [], "exit": False}
        self.cell_entry = None
        self.proof_mode = False

    # ---- capabilities (mirror of Rust Caps)
    @staticmethod
    def _norm_path(p):
        out = []
        for seg in p.split("/"):
            if seg in ("", "."):
                continue
            if seg == "..":
                if out:
                    out.pop()
            else:
                out.append(seg)
        return "/".join(out)

    @staticmethod
    def _resolved(p):
        try:
            return os.path.realpath(p)
        except OSError:
            return p

    def _path_allowed(self, cap, what):
        # resolved-prefix comparison (symlink-aware, like the Rust core)
        rw = self._resolved(what)
        for g in self.caps[cap]:
            rg = self._resolved(g)
            if rw == rg or rw.startswith(rg + os.sep):
                return True
            # non-existent target: nearest existing ancestor must resolve inside
            probe = what
            parent = os.path.dirname(probe)
            if parent and parent != probe:
                rp = self._resolved(parent)
                if rp == rg or rp.startswith(rg + os.sep):
                    return True
        # lexical fallback for grants that do not exist on disk
        np = self._norm_path(what)
        for g in self.caps[cap]:
            ng = self._norm_path(g)
            if ng != "" and (np == ng or np.startswith(ng + "/")):
                return True
        return False

    def cap_check(self, cap, kind, what):
        c = self.caps
        if not c["enabled"] or "*" in c[cap]:
            return
        ok = False
        if kind in ("read", "write"):
            ok = self._path_allowed(cap, what)
        else:
            ok = what in c[cap]
        if not ok:
            raise Stress("interference", f"{kind} denied, no capability grant covers '{what}' (grant with --allow-{kind} or --allow-all)")

    def new_scope(self, parent):
        return {"__parent__": parent}

    def lookup(self, env, name):
        node = env
        while node is not None:
            if name in node:
                return node[name]
            node = node["__parent__"]
        return None

    def find_env(self, env, name):
        node = env
        while node is not None:
            if name in node:
                return node
            node = node["__parent__"]
        return None

    def assign(self, env, name, val):
        target = self.find_env(env, name)
        if target is None:
            env[name] = val
            return False
        target[name] = val
        return True

    def is_const(self, env, name):
        node = env
        while node is not None:
            if ("__const__", name) in node:
                return True
            node = node.get("__parent__")
        return False

    def deep_freeze(self, v):
        seen = set()
        self._freeze_walk(v, seen)

    def _freeze_walk(self, v, seen):
        # W05 hardening (rt_p18a): ITERATIVE worklist (depth-safe on deep
        # literals) + keep-alive registration (address/id-reuse armor),
        # mirroring the Rust frozen_keep registry.
        work = [v]
        while work:
            cur = work.pop()
            if isinstance(cur, list):
                p = id(cur)
                if p in seen:
                    continue
                seen.add(p)
                self.frozen_ids.add(p)
                self.frozen_keep.append(cur)
                work.extend(cur)
            elif isinstance(cur, dict):
                p = id(cur)
                if p in seen:
                    continue
                seen.add(p)
                self.frozen_ids.add(p)
                self.frozen_keep.append(cur)
                for k, val in cur.items():
                    work.append(k)
                    work.append(val)
                for k, val in _map_items_side(cur):
                    work.append(k)
                    work.append(val)

    def is_frozen(self, v):
        return isinstance(v, (list, dict)) and id(v) in self.frozen_ids

    @staticmethod
    def _frozen_stress(what):
        return Stress("frozen", f"cannot modify frozen {what}")

    def _park_frozen_reachable(self, roots):
        """Spawn boundary: the Rust worker receives serialized COPIES of the
        arguments, so no container reachable from an argument is frozen inside
        the worker. The sequential oracle runs the body inline against the
        SAME objects, park the reachable ids for the body, restore after."""
        parked = set()
        seen = set()

        def walk(v):
            if isinstance(v, list):
                if id(v) in seen:
                    return
                seen.add(id(v))
                if id(v) in self.frozen_ids:
                    parked.add(id(v))
                    self.frozen_ids.discard(id(v))
                for item in v:
                    walk(item)
            elif isinstance(v, dict):
                if id(v) in seen:
                    return
                seen.add(id(v))
                if id(v) in self.frozen_ids:
                    parked.add(id(v))
                    self.frozen_ids.discard(id(v))
                for k, val in v.items():
                    walk(k)
                    walk(val)
                for k, val in _map_items_side(v):
                    walk(k)
                    walk(val)

        for r in roots:
            walk(r)
        return parked

    def _restore_frozen(self, parked):
        self.frozen_ids |= parked

    def note(self, rung, msg, line=0):
        # Z-CAPWINDOW (L-053) mirror of Interp::note: sec-r3 — past the 10k
        # cap (the COMBINED list: parse notes were pushed in raw by the
        # runner, exactly like tools.rs `interp.notes.push(n.clone())`),
        # further eval notes are counted, not stored; one boundary note at
        # the first drop.
        NOTE_CAP = 10_000
        if len(self.notes) >= NOTE_CAP:
            self.notes_dropped += 1
            if self.notes_dropped == 1:
                self.notes.append(Note(4, "note cap (10000) reached, further notes suppressed", line))
            return
        # loop-9 (C8): worker-note prefix parity — the Rust join path tags
        # every spawned worker note with "[task <name>] " (genes.rs); the
        # sequential oracle applies the same prefix while the spawn body
        # runs inline, so cross-cell notes are byte-identical.
        prefix = getattr(self, "task_note_prefix", None)
        if prefix:
            msg = f"{prefix} {msg}"
        # compat matrix fix: notes carry the origin line (ast.rs parity);
        # load_file threads the parser note's line through here
        self.notes.append(Note(rung, msg, line))

    def tick(self):
        self.steps += 1
        if self.steps > 20_000_000:
            raise Stress("overflow", "step budget exhausted")
