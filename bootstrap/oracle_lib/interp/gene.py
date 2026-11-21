"""operon oracle: interp.gene (split of bootstrap/oracle.py)."""

from ..annot import ann_is_typaram, ann_matches, ann_render, type_name
from ..fmt import truthy
from ..values import M64, ObjInst, Return, Stress



class IGene:

    def call_gene_inner(self, g, args):
        name = g.name or "<lambda>"
        # GRN gate first: a suppressed call is not expression, it must not
        # reach the call counters, the burst bins, or the gene body.
        veto = self.grn_veto(name)
        if veto is not None:
            self.note(4, f"grn gate: '{name}' call suppressed ({veto})")
            return None
        # T2b methylation gate: level >= threshold blocks transcription;
        # @acetylate genes are exempt (open chromatin wins, D-005).
        if not g.acetylate:
            lvl = self.methyl_levels.get(name, 0)
            if lvl >= self.methyl_threshold:
                self.note(4, f"methylation silences: '{name}' (level {lvl} >= threshold {self.methyl_threshold}), call returns null")
                return None
        # loop-9 (F-5): CIS riboswitch, after chromatin, before the
        # promoter. The pinned order extends to
        # RISC → toggle → GRN → methylation → riboswitch → promoter.
        if g.riboswitch is not None:
            lig, on, rt = g.riboswitch
            lvl = self._ligand_level(lig)
            bound = lvl >= rt
            veto = (not bound) if on else bound
            if veto:
                why = "unbound: RBS sequestered" if on else "bound: terminator hairpin folded"
                self.note(4, f"riboswitch '{lig}' {why}: '{name}' call suppressed")
                return None
        # reg-bio (F-1): telegraph promoter layer, the pinned gate order
        # ends here: RISC → toggle → GRN → methylation → riboswitch → promoter.
        if self._promoter_veto(name, g.burst):
            self.note(4, f"promoter inactive: '{name}' burst-off, call returns null")
            return None
        # loop-10 (F-7): Rho-dependent termination (mirror), opt-in (.cell
        # rho.termination = true). Pinned gate order ends: ... promoter → RHO.
        # Naked upstream RNA scan in member order: p_g = 1 (methylated) or
        # 1 − surv(g) (target-less RISC silence) or 0; draws only where
        # 0 < p_g < 1 (member order) then one catch-up draw where 0 < q < 1;
        # catch probability compounding over the naked runway (no pow; the
        # R10 W1 fix, pressure GROWS with distance); F-8 shield: queue
        # >= rho.queue_floor occludes the rut sites. A terminated call is
        # not expression: returns null before counters/transcript/queue.
        rho_on, rho_catch, rho_floor, rho_cap, _drain = self._rho_knobs()
        if rho_on:
            rui = self._operon_of(name)
            if rui is not None:
                pos = next(i for i, (m, _r) in enumerate(self.operons[rui]["members"]) if m == name)
                terminated = None
                for i in range(pos):
                    g2 = self.operons[rui]["members"][i][0]
                    if self.methyl_levels.get(g2, 0) >= self.methyl_threshold:
                        p_g = 1.0
                    else:
                        surv = 1.0
                        has_silence = False
                        for f3, t3, s3, n3 in self.silences:
                            if f3 == g2 and t3 is None:
                                has_silence = True
                                base = 1.0 - s3
                                for _k in range(n3):
                                    surv *= base
                        p_g = (1.0 - surv) if has_silence else 0.0
                    if p_g == 0.0:
                        continue
                    x = self.rng
                    if 0.0 < p_g and p_g < 1.0:
                        x ^= (x >> 12) & M64
                        x ^= (x << 25) & M64
                        x ^= (x >> 27) & M64
                        self.rng = x & M64
                    if p_g == 1.0:
                        naked_g = True
                    else:
                        x = self.rng
                        u = ((x >> 11) & ((1 << 53) - 1)) / 9007199254740992.0
                        naked_g = u < p_g
                    shielded = self.ribo_queue.get(g2, 0.0) >= rho_floor
                    if naked_g and not shielded:
                        # q = 1 - (1-catch)^d, per-cistron catch compounding
                        # over the naked runway (mirror of the Rust W1 fix:
                        # catch^d had the distance profile inverted, the
                        # FURTHER downstream the reader, the MORE time Rho
                        # has had to catch up)
                        per = 1.0 - rho_catch
                        surv = 1.0
                        for _k in range(pos - i):
                            surv *= per
                        q = 1.0 - surv
                        if q == 0.0:
                            break
                        x2 = self.rng
                        if 0.0 < q and q < 1.0:
                            x2 ^= (x2 >> 12) & M64
                            x2 ^= (x2 << 25) & M64
                            x2 ^= (x2 >> 27) & M64
                            self.rng = x2 & M64
                        if q == 1.0:
                            caught = True
                        else:
                            x2 = self.rng
                            u2 = ((x2 >> 11) & ((1 << 53) - 1)) / 9007199254740992.0
                            caught = u2 < q
                        if caught:
                            terminated = g2
                        break
                if terminated is not None:
                    self.note(4, f"rho terminated: transcript lost at '{terminated}', call returns null")
                    return None
        # reg-bio-3 (A1/A7): the call passed every gate, one transcript of
        # the unit is made (a suppressed call is NOT expression) (mirror)
        ui = self._operon_of(name)
        if ui is not None:
            self.operons[ui]["transcripts"] += 1
            # loop-10 (F-8): ribosome queue register (mirror), every
            # member's queue grows by its rbs, capped at ribosome.queue_cap;
            # rho.termination-gated (inert bookkeeping otherwise).
            if rho_on:
                for m2, rbs2 in self.operons[ui]["members"]:
                    nv = self.ribo_queue.get(m2, 0.0) + rbs2
                    self.ribo_queue[m2] = rho_cap if nv > rho_cap else nv
        self.call_counts[name] = self.call_counts.get(name, 0) + 1
        self.call_clock += 1
        # reg-bio-2 (C2): the decay clock (mirror of the Rust hook)
        self._grn_decay_tick()
        bucket = self.call_clock // 20
        self.gene_buckets.setdefault(name, {}).setdefault(bucket, 0)
        self.gene_buckets[name][bucket] += 1
        if g.methylate and not self.methyl_quiet and name not in self.methyl_noted:
            self.methyl_noted.add(name)
            self.note(4, f"methylated call: '{name}' (chromatin repressed)")
        fenv = self.new_scope(g.closure if g.closure is not None else self.globals)
        for i, (pname, dflt) in enumerate(g.params):
            if pname in ("?", ""):
                continue
            if i < len(args):
                # W01 (L2c): soft param annotation at the funnel (mirror).
                anns = g.param_anns
                if i < len(anns) and anns[i] is not None and not ann_is_typaram(anns[i], g.type_params) and not ann_matches(args[i], anns[i]):
                    raise Stress("unfolded", f"argument '{pname}' for gene '{name}' expects {ann_render(anns[i])}, got {type_name(args[i])}")
                fenv[pname] = args[i]
            elif dflt is not None:
                dv = self.eval_expr(fenv, dflt)
                anns = g.param_anns
                if i < len(anns) and anns[i] is not None and not ann_is_typaram(anns[i], g.type_params) and not ann_matches(dv, anns[i]):
                    raise Stress("unfolded", f"default of '{pname}' for gene '{name}' expects {ann_render(anns[i])}, got {type_name(dv)}")
                fenv[pname] = dv
            else:
                self.note(4, f"missing argument '{pname}' in call to {name}; bound null", g.line)
                fenv[pname] = None
        if len(args) > len(g.params) and g.params:
            self.note(4, f"{len(args) - len(g.params)} extra argument(s) in call to {name} ignored", g.line)
        if g.guard is not None:
            cond, gbody = g.guard
            ok = False
            try:
                ok = truthy(self.eval_expr(fenv, cond))
            except Stress:
                ok = False
            if not ok:
                self.note(4, f"guard tripped calling {name}")
                try:
                    self.exec_block(fenv, gbody)
                    self.note(4, f"guard of {name} returned null (uORF repression)")
                    return None
                except Return as r:
                    return r.value
                except Stress as st:
                    # W06 (D-014) mirror: propagation from a guard body returns
                    # from the gene (same contract as a guard `return`).
                    if st.prop is not None:
                        return st.prop
                    raise
        try:
            self.exec_block(fenv, g.body)
            # no explicit return → null; a non-optional return annotation is
            # violated by the implicit null too (mirror of interp.rs)
            return self._check_ret(name, g, None, False)
        except Return as r:
            return self._check_ret(name, g, r.value, True)
        except Stress as st:
            # W06 (D-014) mirror: a propagated variant IS the gene's return
            # value, the signal unwinds here and becomes the result.
            if st.prop is not None:
                return self._check_ret(name, g, st.prop, True)
            raise

    def _check_ret(self, name, g, v, explicit):
        """W01 (L2c): soft return annotation, checked on the value the gene
        actually returns (including a `?!`-propagated variant)."""
        if g.ret_ann is None:
            return v
        if explicit:
            if not ann_is_typaram(g.ret_ann, g.type_params) and not ann_matches(v, g.ret_ann):
                raise Stress("unfolded", f"return of gene '{name}' expects {ann_render(g.ret_ann)}, got {type_name(v)}")
        else:
            if not ann_is_typaram(g.ret_ann, g.type_params) and not ann_matches(None, g.ret_ann):
                raise Stress("unfolded", f"return of gene '{name}' expects {ann_render(g.ret_ann)}, got null (no return statement ran)")
        return v

    # ---- methods
    def call_method_gene(self, g, self_val, args):
        self.depth += 1
        if self.depth > self.depth_limit:
            self.depth -= 1
            raise Stress("overflow", f"recursion depth limit ({self.depth_limit}) exceeded")
        try:
            name = g.name or "<method>"
            # T2b methylation gate for phenotype methods (same contract).
            if not g.acetylate:
                lvl = self.methyl_levels.get(name, 0)
                if lvl >= self.methyl_threshold:
                    self.note(4, f"methylation silences: '{name}' (level {lvl} >= threshold {self.methyl_threshold}), call returns null")
                    return None
            # reg-bio (F-1): promoter gate (funnel order preserved)
            if self._promoter_veto(name):
                self.note(4, f"promoter inactive: '{name}' burst-off, call returns null")
                return None
            self.call_counts[name] = self.call_counts.get(name, 0) + 1
            self.call_clock += 1
            # reg-bio-2 (C2): the decay clock (mirror of the Rust hook)
            self._grn_decay_tick()
            bucket = self.call_clock // 20
            self.gene_buckets.setdefault(name, {}).setdefault(bucket, 0)
            self.gene_buckets[name][bucket] += 1
            if g.methylate and not self.methyl_quiet and name not in self.methyl_noted:
                self.methyl_noted.add(name)
                self.note(4, f"methylated call: '{name}' (chromatin repressed)")
            fenv = self.new_scope(self.globals)
            fenv["self"] = self_val
            for i, (pname, dflt) in enumerate(g.params):
                if pname in ("?", "", "self"):
                    continue
                if i < len(args):
                    # W01 (L2c): method param annotations, same soft contract.
                    anns = g.param_anns
                    if i < len(anns) and anns[i] is not None and not ann_is_typaram(anns[i], g.type_params) and not ann_matches(args[i], anns[i]):
                        raise Stress("unfolded", f"argument '{pname}' for method '{name}' expects {ann_render(anns[i])}, got {type_name(args[i])}")
                    fenv[pname] = args[i]
                elif dflt is not None:
                    fenv[pname] = self.eval_expr(fenv, dflt)
                else:
                    fenv[pname] = None
            if g.guard is not None:
                cond, gbody = g.guard
                try:
                    ok = truthy(self.eval_expr(fenv, cond))
                except Stress:
                    ok = False
                if not ok:
                    self.note(4, f"guard tripped calling {name}")
                    try:
                        self.exec_block(fenv, gbody)
                        return self._check_ret_method(name, g, None, False)
                    except Return as r:
                        return self._check_ret_method(name, g, r.value, True)
                    except Stress as st:
                        # W06 (D-014) mirror: guard-body propagation returns
                        # from the method (same contract as a guard `return`).
                        if st.prop is not None:
                            return self._check_ret_method(name, g, st.prop, True)
                        raise
            try:
                self.exec_block(fenv, g.body)
                return self._check_ret_method(name, g, None, False)
            except Return as r:
                return self._check_ret_method(name, g, r.value, True)
            except Stress as st:
                # W06 (D-014) mirror: a propagated variant IS the method's
                # return value.
                if st.prop is not None:
                    return self._check_ret_method(name, g, st.prop, True)
                raise
        finally:
            self.depth -= 1

    def _check_ret_method(self, name, g, v, explicit):
        """W01 (L2c): method return annotation, same soft contract."""
        if g.ret_ann is None:
            return v
        if explicit:
            if not ann_is_typaram(g.ret_ann, g.type_params) and not ann_matches(v, g.ret_ann):
                raise Stress("unfolded", f"return of method '{name}' expects {ann_render(g.ret_ann)}, got {type_name(v)}")
        else:
            if not ann_is_typaram(g.ret_ann, g.type_params) and not ann_matches(None, g.ret_ann):
                raise Stress("unfolded", f"return of method '{name}' expects {ann_render(g.ret_ann)}, got null (no return statement ran)")
        return v

    def _weak_binding_alive(self, env, addr):
        # is the weak target still strongly referenced by ANY name binding on
        # the live scope chain? (containers that merely hold the value are a
        # Rust-lane shape the differential corpus deliberately avoids)
        node = env
        while node is not None:
            for val in node.values():
                if isinstance(val, ObjInst):
                    if id(val.fields) == addr:
                        return True
                elif id(val) == addr:
                    return True
            node = node["__parent__"]
        return False
