"""operon oracle: interp.grn (split of bootstrap/oracle.py)."""

from ..values import M64, repressilator_levels



class IGrn:

    def grn_veto(self, name):
        """reg-bio-3 (A1/A7): the call gate. A call to a cistron of a
        polycistronic unit is a transcription attempt of the WHOLE unit:
        edges targeting the unit veto every member first (induction acts
        on the unit's promoter), then the cistron's own edges apply.
        The unit pass short-circuits, its message wins. (mirror)"""
        if not self.grn_edges:
            return None
        ui = self._operon_of(name)
        if ui is not None:
            uname = self.operons[ui]["name"]
            if any(e[1] == uname for e in self.grn_edges):
                reason = self._gate_veto_for(uname)
                if reason is not None:
                    return f"operon '{uname}': {reason}"
        return self._gate_veto_for(name)

    def _operon_of(self, gene):
        """reg-bio-3 (A1/A7): index of the unit owning `gene`, if any."""
        for i, u in enumerate(self.operons):
            if any(m == gene for m, _r in u["members"]):
                return i
        return None

    def _gate_veto_for(self, name):
        """GRN cis-gate for ONE target (T2a / SPEC §11), mirror of the
        Rust core (the pinned body, target as a parameter).

        Activating edge with explicit threshold t vetoes while
        level(source) < t; inhibiting edge with explicit threshold t vetoes
        while level(inhibitor) >= t; edges without a threshold stay
        declarative; a threshold of 0 never blocks (back-compat).
        T2e: an enhance'd gene lowers its activating thresholds by
        ENHANCE_DELTA (0.25)."""
        if not self.grn_edges:
            return None
        boosted = name in self.enhanced
        veto = None
        # reg-bio (F-3): AND/OR cis-regulatory logic, first-wins message
        # order preserved exactly (mirror of the Rust grn_veto). The gate
        # opens iff (every AND member passes) OR (any OR member passes),
        # an `any` edge is an ALTERNATIVE activator that alone suffices.
        and_fail = None
        and_present = False
        or_present = False
        or_pass = False
        for frm, to, st, inh, thr, hill, is_any, occupy, is_sum, attenuating in self.grn_edges:
            if veto is not None:
                break
            if to != name:
                continue
            # reg-bio-2 (B7): sum edges are pooled members, evaluated by the
            # group pass below, never as individual AND members (mirror).
            if is_sum:
                continue
            # reg-bio-2 (C11 + A4): regulation reads the DNA-available
            # fraction (mirror of the Rust veto).
            lvl = self._regulated_level(self._grn_level(frm), frm)
            if inh:
                if thr is not None and lvl >= thr and and_fail is None:
                    # reg-bio-2 (A5): an `attenuates` edge reports the
                    # RNA-level mechanism (leader-termination outcome).
                    if attenuating:
                        veto = f"attenuator '{frm}' level {lvl!r} >= threshold {thr!r} (leader terminated)"
                    else:
                        veto = f"inhibitor '{frm}' level {lvl!r} >= threshold {thr!r}"
            elif thr is not None:
                t = thr
                if boosted:
                    t = max(0.0, t - self.enhance_delta)
                if is_any:
                    or_present = True
                    if lvl >= t:
                        or_pass = True
                else:
                    and_present = True
                    if lvl < t and and_fail is None:
                        and_fail = f"regulator '{frm}' level {lvl!r} < threshold {t!r}"
        # reg-bio-2 (B7): pooled (`sum`) edges, group pass (mirror of the
        # Rust grn_veto). Groups keyed by (target, threshold, hill) pool
        # weighted inputs P = min(1, Σ s·lvl); each group acts as ONE
        # conjunctive member passing iff P >= t (with the enhance boost).
        if veto is None:
            groups = []
            for frm, to, st, inh, thr, hill, is_any, occupy, is_sum, attenuating in self.grn_edges:
                if inh or not is_sum or to != name:
                    continue
                if thr is None or thr <= 0.0:
                    continue
                lvl = self._regulated_level(self._grn_level(frm), frm)
                n_h = hill if hill is not None else 2
                for g in groups:
                    if g[0] == to and g[1] == thr and g[2] == n_h:
                        g[3] += st * lvl
                        break
                else:
                    groups.append([to, thr, n_h, st * lvl])
            for to, thr, _n, pooled in groups:
                p = min(pooled, 1.0)
                t = thr
                if boosted:
                    t = max(0.0, t - self.enhance_delta)
                if p < t and and_fail is None:
                    and_fail = f"pooled regulators of '{to}' level {p!r} < threshold {t!r}"
        if veto is None and not or_pass:
            if and_fail is not None:
                veto = and_fail
            elif or_present and not and_present:
                veto = "no OR activator above threshold"
        return veto

    def _grn_level(self, frm):
        """A11 (reg-r2): mirror of the Rust grn_veto level resolution,
        explicit grn levels first, then the repressilator ring overlay
        (normalized raw/α, clamped 0..1) so the emergent oscillator
        genuinely drives downstream genes.
        reg-bio-2 (C11): the read returns the FREE fraction, decoy sites
        sequester their regulator (competitive titration, mirror of the
        Rust regulated_level)."""
        if frm in self.grn_levels:
            lvl = self.grn_levels[frm]
        elif self.repressi_ring and frm in self.repressi_ring:
            idx = self.repressi_ring.index(frm)
            lvls = repressilator_levels(len(self.repressi_ring), self.repressi_tick, self.repressi_params)
            lvl = min(lvls[idx] / self.repressi_params["alpha"], 1.0)
        elif frm in self.ligands:
            # reg-bio-2 (A4/C7): a ligand edge source reads its metabolite
            # pool, a riboswitch-style, protein-free gate (mirror).
            lvl = self._ligand_level(frm)
        elif frm in self.signals:
            # loop-9 (C8): a signal species reads the shared medium (the
            # LuxR-AHL population gate, mirror of Rust signal_level).
            lvl = self._signal_level(frm)
        else:
            lvl = 0.0
        return lvl

    def _signal_register(self, name):
        """loop-9 (C8): mirror of Rust signal_register, idempotent, cap 64."""
        if name in self.signals:
            return True
        if len(self.signals) >= 64:
            self.note(4, f"signal species cap (64) reached: '{name}' not registered")
            return False
        self.signals.append(name)
        return True

    def _signal_level(self, name):
        """loop-9 (C8): mirror of Rust signal_level, molecules / 1e9, ONE
        division (counts capped at 1e9 < 2**53, so the double is identical)."""
        return self.medium.get(name, 0) / 1e9

    def _ligand_level(self, name):
        """reg-bio-2 (A4): mirror of the Rust ligand_level, the runtime pool
        (`ligand_set`) wins; the `.cell [ligand.<name>]` bath is the default."""
        if name in self.ligand_pools:
            return self.ligand_pools[name]
        raw = self.cell.get("ligand." + name)
        if raw is None:
            return 0.0
        try:
            return min(max(float(raw), 0.0), 1.0)
        except ValueError:
            return 0.0

    def _regulated_level(self, raw, frm):
        """reg-bio-2 (C11 + A4): mirror of the Rust regulated_level, the
        DNA-available fraction: (1) decoy titration (subtractive), then
        (2) allosteric modulation (inducers: Π(1 − occ), cofactors: Π occ,
        occ = L/(k+L))."""
        l = raw
        for d, tf, cap in self.decoys:
            if tf == frm:
                l -= cap * self.grn_levels.get(d, 0.0)
        if l < 0.0:
            l = 0.0
        factor = 1.0
        for tf, lg, inducer, k in self.grn_binds:
            if tf == frm:
                lig = self._ligand_level(lg)
                occ = (lig / (k + lig)) if k > 0.0 else 1.0
                factor *= (1.0 - occ) if inducer else occ
        out = l * factor
        # reg-bio-3 (C10): gene dosage, @copies amplifies the CONCENTRATION
        # the gene feeds its edges, saturating on the 0..1 lattice (mirror)
        c = self.copies.get(frm)
        if c is not None and c > 1:
            out *= c
        return out if out <= 1.0 else 1.0

    def _rho_knobs(self):
        """loop-10 (F-7/F-8): mirror of the Rust rho_knobs, (armed, catch,
        queue_floor, queue_cap, drain). Host: .cell parsed per use (garbage
        falls back identically: catch clamps 0..1, the rest parse-or-default);
        worker: the pinned snapshot tuple. Default-off: absent
        rho.termination = false, legacy runs draw nothing, bit-identical."""
        if self.rho_pins is not None:
            return self.rho_pins
        armed = self.cell.get("rho.termination") == "true"
        catch = self.cell.get("rho.catch")
        try:
            catch = min(max(float(catch), 0.0), 1.0) if catch is not None else 0.5
        except ValueError:
            catch = 0.5

        def _g(key, dflt):
            v = self.cell.get(key)
            try:
                return float(v) if v is not None else dflt
            except (TypeError, ValueError):
                return dflt

        return (armed, catch, _g("rho.queue_floor", 0.5), _g("ribosome.queue_cap", 1.0), _g("ribosome.drain", 0.5))

    def _trans_integrate(self):
        """reg-bio-2 (C1): mirror of the Rust trans_integrate, one Euler
        step per translates edge: p += rate·Δcalls − decay·p (clamped 0..1)
        where Δcalls is the source's call-count delta since the last
        integration (checkpoints start at 0)."""
        # loop-10 (F-8 + R10 kinetics jury L1): ribosome queue drain (mirror)
        #, at ENTRY (before the empty-check: "every integration point") and
        # before the edge loop (pinned order; both entry points reach
        # _trans_integrate). Exists only under rho.termination; max(0.0) is
        # mirror-safe.
        rho_on, _c, _fl, _cap, rho_drain = self._rho_knobs()
        if rho_on:
            for k2 in list(self.ribo_queue):
                self.ribo_queue[k2] = max(0.0, self.ribo_queue[k2] - rho_drain)
        if not self.trans_edges:
            return
        for frm, to, rate, pdecay in self.trans_edges:
            key = frm + "\u0000" + to
            now = self.call_counts.get(frm, 0)
            last = self.trans_last.get(key, 0)
            self.trans_last[key] = now
            delta = now - last
            if delta < 0:
                delta = 0
            dec = pdecay if pdecay is not None else 0.0
            # loop-9 (F-6): m6A reader fate (mirror), engage only at mark
            # density >= min_level (default 2); the {0,1} legacy lattice is
            # bit-identical. Knobs: .cell m6a.reader.decay (0.25) /
            # m6a.reader.translation (0.10) / m6a.reader.min_level (2).
            yd2 = self.cell.get("m6a.reader.decay")
            try:
                yd2 = min(max(float(yd2), 0.0), 1.0) if yd2 is not None else 0.25
            except ValueError:
                yd2 = 0.25
            yatt = self.cell.get("m6a.reader.translation")
            try:
                yatt = min(max(float(yatt), 0.0), 1.0) if yatt is not None else 0.10
            except ValueError:
                yatt = 0.10
            minl = self.cell.get("m6a.reader.min_level")
            try:
                minl = min(max(int(minl), 0), 3) if minl is not None else 2
            except ValueError:
                minl = 2
            reader = self.m6a_levels.get(frm, 0) >= minl
            dec_eff = dec + yatt if reader else dec
            if delta == 0 and dec_eff == 0.0:
                continue
            r = rate if rate is not None else 1.0
            # reg-bio-3 (A1/A7): per-cistron rbs efficiency + transcriptional
            # polarity (upstream blocking reduces downstream yield) (mirror)
            # loop-9 (P0-1): per-call-WEIGHTED polarity (mirror), each
            # upstream member contributes its expected factor: methylation
            # past threshold => pol; a target-less RISC silence with capture
            # p = 1 − Π(1−s_i)^sites_i => surv + (1−surv)·pol with
            # surv = Π(1−s_i)^sites_i; nothing => 1.0. Legacy inputs
            # degenerate to exactly 1.0 or pol in the same member order,
            # bit-identical to the old binary rule; no randomness consumed.
            ui = self._operon_of(frm)
            if ui is not None:
                u = self.operons[ui]
                pos = next(i for i, (m, _r) in enumerate(u["members"]) if m == frm)
                r *= u["members"][pos][1]
                # loop-10 (W2, R10 biology jury): under Rho ON the polarity
                # factor is IDENTITY, D2 resolves the upstream failure per
                # call, so a surviving transcript translates at full rate
                # (D1's expected-value derate would double-count the same
                # loss). Rho OFF keeps the exact legacy fold (bit-identical).
                if not rho_on:
                    pol = self.cell.get("operon.polarity")
                    pv = 0.5
                    if pol is not None:
                        try:
                            pv = min(max(float(pol), 0.0), 1.0)
                        except ValueError:
                            pv = 0.5
                    f2 = 1.0
                    for g2, _r2 in u["members"][:pos]:
                        methylated = self.methyl_levels.get(g2, 0) >= self.methyl_threshold
                        if methylated:
                            factor = pv
                        else:
                            surv = 1.0
                            silenced = False
                            for f3, t3, s3, n3 in self.silences:
                                if f3 == g2 and t3 is None:
                                    silenced = True
                                    base = 1.0 - s3
                                    for _k in range(n3):
                                        surv *= base
                            if silenced:
                                factor = surv + (1.0 - surv) * pv
                            else:
                                factor = 1.0
                        f2 *= factor
                    r *= f2
            # loop-9 (F-6): YTHDF2 decay routing, the LAST production
            # multiply (normative order: rate x rbs x polarity x (1-yd2))
            if reader:
                r *= 1.0 - yd2
            cur = self.grn_levels.get(to, 0.0)
            p = cur + r * delta - dec_eff * cur
            if p < 0.0:
                p = 0.0
            if p > 1.0:
                p = 1.0
            self.grn_levels[to] = p

    def _grn_decay_tick(self):
        """reg-bio-2 (C2): mirror of the Rust grn_decay_tick, the
        decay_clock builtin overrides the .cell keys (`grn.decay_calls`/
        `grn.decay`); one decay step every N calls, then translation
        integrates. Unset = no-op (byte-identical event-driven contract)."""
        if self.decay_clock_n is not None:
            n = self.decay_clock_n
        else:
            raw = self.cell.get("grn.decay_calls")
            if raw is None:
                return
            try:
                n = int(raw)
            except (TypeError, ValueError):
                return
            if n <= 0:
                return
        if self.call_clock % n != 0:
            return
        if self.decay_clock_f is not None:
            decay = self.decay_clock_f
        else:
            d = self.cell.get("grn.decay")
            decay = 0.0
            if d is not None:
                try:
                    decay = min(max(float(d), 0.0), 1.0)
                except ValueError:
                    decay = 0.0
        if decay > 0.0 and self.grn_levels:
            retention = 1.0 - decay
            for k2 in list(self.grn_levels):
                self.grn_levels[k2] *= retention
                if self.grn_levels[k2] < 2.220446049250313e-16:
                    self.grn_levels[k2] = 0.0
        # reg-bio-3 (B3): m6A decay, `.cell m6a.decay f` erases site
        # density as time passes (half-down rounding on the 0..=3 lattice;
        # a diluted mark never reads as MORE marked). Unset = byte-identical.
        mdecay = self.cell.get("m6a.decay")
        if mdecay is not None and self.m6a_levels:
            try:
                mf = min(max(float(mdecay), 0.0), 1.0)
            except ValueError:
                mf = 0.0
            if mf > 0.0:
                import math as _math
                for k2 in list(self.m6a_levels):
                    x = self.m6a_levels[k2] * (1.0 - mf) - 0.5
                    self.m6a_levels[k2] = max(0, int(_math.ceil(x)))
        self._trans_integrate()

    def _promoter_veto(self, name, burst=None):
        """reg-bio (F-1): telegraph promoter draw, mirror of the Rust
        promoter_veto. One draw per call attempt on the SHARED xorshift64*
        stream (the `random()` state machine): active → off with p=koff,
        inactive → on with p=kon. State persists across calls (the burst).
        loop-9 (F-2): a per-gene @burst mark overrides (kon, koff) for THIS
        gene only, promoter identity. loop-9 (F-3): attempt telemetry."""
        if not self.expr_stochastic:
            return False
        if burst is None:
            burst = self.burst_overrides.get(name)
        kon, koff = burst if burst is not None else (self.expr_kon, self.expr_koff)
        was_active = self.promoter_states.get(name, True)
        x = self.rng
        x ^= (x >> 12) & M64
        x ^= (x << 25) & M64
        x ^= (x >> 27) & M64
        self.rng = x & M64
        x = self.rng
        u = ((x >> 11) & ((1 << 53) - 1)) / 9007199254740992.0
        if was_active:
            now_active = u >= koff
        else:
            now_active = u < kon
        self.promoter_states[name] = now_active
        e = self.promoter_tel.get(name, (0, 0, 0))
        self.promoter_tel[name] = (e[0] + 1, e[1] + (1 if now_active else 0), e[2] + (1 if (not now_active) and was_active else 0))
        if not now_active:
            self.burst_off[name] = self.burst_off.get(name, 0) + 1
            return True
        return False
