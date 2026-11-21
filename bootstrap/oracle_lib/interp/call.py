"""operon oracle: interp.call (split of bootstrap/oracle.py)."""

from ..annot import type_name
from ..interp.builtin_tables import BUILTINS, BUILTIN_SYNONYMS
from ..lexer import edit_distance
from ..values import Gene, M64, SeqObj, Stress



class ICall:

    # ---- calls
    def call_value(self, env, callee, args):
        if isinstance(callee, Gene):
            if not callee.seq:
                # reg-r4 (re-audit B-5): value-bound (higher-order) gene calls
                # pass the toggle gate too, "the pair gates calls" is
                # unqualified; the seq branch already gated, genes did not
                gname = callee.name or "<lambda>"
                for a, b, a_on in self.toggles:
                    if a == gname or b == gname:
                        this_is_a = a == gname
                        active = (a_on and this_is_a) or ((not a_on) and (not this_is_a))
                        if not active and not callee.acetylate:
                            winner = a if a_on else b
                            self.note(4, f"toggle repressed: '{gname}' is the inactive allele ('{winner}' is on)")
                            return None
                        break
            if callee.seq:
                # reg-r3 (re-audit): sequences honor ALL creation gates,
                # GRN veto, methylation, toggle, in call_gene_inner order
                # (mirror of the Rust branch; reg-r1 gated only the toggle)
                seq_name = callee.name or "<seq>"
                dl = getattr(callee, "line", 0)
                veto = self.grn_veto(seq_name)
                if veto is not None:
                    self.note(4, f"grn gate: sequence '{seq_name}' call suppressed ({veto})")
                    return None
                if not callee.acetylate:
                    lvl = self.methyl_levels.get(seq_name, 0)
                    if lvl >= self.methyl_threshold:
                        self.note(4, f"methylation silences: sequence '{seq_name}' (level {lvl} >= threshold {self.methyl_threshold}), call returns null")
                        return None
                # reg-r4 (re-audit B-1): the toggle gate was missing here,
                # a toggle-repressed sequence created via a value binding
                # transcribed in the oracle while the Rust core refused it
                for a, b, a_on in self.toggles:
                    if a == seq_name or b == seq_name:
                        this_is_a = a == seq_name
                        active = (a_on and this_is_a) or ((not a_on) and (not this_is_a))
                        if not active and not callee.acetylate:
                            winner = a if a_on else b
                            self.note(4, f"toggle repressed: sequence '{seq_name}' is the inactive allele ('{winner}' is on)")
                            return None
                        break
                # reg-bio (F-1): promoter gate last, the pinned funnel order
                # ends here (bursting is the promoter's own stochastic
                # dynamics; no @acetylate exemption, open chromatin bursts too)
                if self._promoter_veto(seq_name, callee.burst):
                    self.note(4, f"promoter inactive: sequence '{seq_name}' burst-off, call returns null")
                    return None
                return SeqObj(self, callee, args)
            return self.call_gene(callee, args)
        self.note(4, f"called a {type_name(callee)} (not a gene); result null")
        return None

    def risc_gate(self, env, name):
        # Z-116 (#116 leg 3): the RISC silencing gate, extracted so it can
        # run BEFORE argument evaluation (the tree-walk order) — the notes,
        # draw order and capture arithmetic are the moved code, verbatim.
        # Returns "degrade", ("redirect", to), or "proceed".
        entries = [e for e in self.silences if e[0] == name]
        if not entries:
            return "proceed"
        target_gene = self.lookup(env, name)
        immune = isinstance(target_gene, Gene) and target_gene.acetylate
        if immune:
            return "proceed"
        surv = 1.0
        for _f, _t, s_i, sites_i in entries:
            base = 1.0 - s_i
            for _k in range(sites_i):
                surv *= base
        p = 1.0 - surv
        captured = True
        if p < 1.0:
            x = self.rng
            x ^= (x >> 12) & M64
            x ^= (x << 25) & M64
            x ^= (x >> 27) & M64
            self.rng = x & M64
            u = ((self.rng >> 11) & ((1 << 53) - 1)) / 9007199254740992.0
            captured = u < p
            if not captured and name not in self.risc_escaped:
                self.risc_escaped.add(name)
                self.note(4, f"RISC escape: '{name}' escaped silencing (strength {entries[0][2]!r}, sites {entries[0][3]})")
        if not captured:
            return "proceed"
        to = entries[0][1]
        if to is not None:
            self.note(4, f"RISC: call to '{name}' silenced → '{to}'")
            return ("redirect", to)
        # reg-bio (F-4): pure degradation, no replacement executes
        self.note(4, f"RISC: call to '{name}' degraded (no replacement)")
        return "degrade"

    def call_named(self, env, name, args, _risc_pre=False):
        if name in BUILTIN_SYNONYMS:
            return self.builtin(env, BUILTIN_SYNONYMS[name], args)
        # reg-r4 (re-audit B-4): gate ORDER is pinned SPEC-wide, RISC at the
        # call site first, then the toggle gate (mirror of the Rust core:
        # silencing wins over repression because it rewrites the callee).
        # RISC silencing: redirect calls (acetylated genes are immune).
        # reg-bio-3 (C9): stoichiometric capture, every entry for the
        # target is one binding site; per-call capture p = 1 - Π(1-s)^sites.
        # strength 1.0 / one site = legacy binary redirect (no draw).
        # Z-116 (#116 leg 3): source-level ident calls run this gate BEFORE
        # their arguments evaluate (eval's call arm) and pass _risc_pre=True;
        # the gate here only serves calls that arrive by other routes.
        if not _risc_pre:
            dec = self.risc_gate(env, name)
            if dec == "degrade":
                return None
            if isinstance(dec, tuple):  # ("redirect", to) — note already emitted
                to = dec[1]
                tgt = self.lookup(env, to)
                return self.call_value(env, tgt, args)
        # toggle gate: the repressed allele refuses calls
        for a, b, a_on in self.toggles:
            if a == name or b == name:
                this_is_a = a == name
                active = (a_on and this_is_a) or ((not a_on) and (not this_is_a))
                target_gene = self.lookup(env, name)
                immune = isinstance(target_gene, Gene) and target_gene.acetylate
                if not active and not immune:
                    winner = a if a_on else b
                    self.note(4, f"toggle repressed: '{name}' is the inactive allele ('{winner}' is on)")
                    return None
                break
        tgt = self.lookup(env, name)
        if tgt is not None or self.find_env(env, name) is not None:
            return self.call_value(env, tgt, args)
        # fate constructor: Name() creates a fate-landscape instance
        if name in self.fates:
            states, enter = self.fates[name]
            return {"#fate": name, "#state": enter or (states[0][0] if states else "")}
        if name in BUILTINS:
            return self.builtin(env, name, args)
        limit2 = 1 if len(name) <= 4 else 2
        best, bd = None, 99
        for b in BUILTINS:
            d = edit_distance(name, b)
            if d <= limit2 and d < bd:
                best, bd = b, d
        if best:
            self.note(3, f"wobble: unknown gene '{name}' repaired to builtin '{best}'")
            return self.builtin(env, best, args)
        best, bd = None, 99
        for g in self.defined_genes:
            d = edit_distance(name, g)
            if d <= limit2 and d < bd:
                best, bd = g, d
        if best and bd > 0:
            self.note(3, f"wobble: unknown gene '{name}' repaired to gene '{best}'")
            gt = self.lookup(env, best)
            return self.call_value(env, gt, args)
        self.note(4, f"phantom call to '{name}'; result null")
        return None

    def call_gene(self, g, args):
        name = g.name or "<lambda>"
        # recursion depth limit (mirror of Rust core)
        self.depth += 1
        if self.depth > self.depth_limit:
            self.depth -= 1
            raise Stress("overflow", f"recursion depth limit ({self.depth_limit}) exceeded")
        # W007 mirror: the traceback frame for THIS gene, captured at entry
        # (cur_line is the call site); appended only on the error path.
        frame = (name, self.cur_line)
        try:
            result = self.call_gene_inner(g, args)
            return result
        except Stress as st:
            # W06 (D-014) mirror: propagation is a return, not a failure, no
            # chain frame. A returned variant is not an error in flight.
            if st.prop is not None:
                raise
            if len(st.chain) < 64:
                st.chain.append(frame)
            raise
        finally:
            self.depth -= 1
