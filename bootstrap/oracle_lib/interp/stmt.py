"""operon oracle: interp.stmt (split of bootstrap/oracle.py)."""

import contextlib
import copy
import os
from ..annot import ann_matches, ann_render, type_name
from ..fmt import truthy, v_display
from ..mapops import _MAP_MISS, _map_insert_key, _map_keys, _map_lookup, _map_member_get
from ..values import BreakLoop, ContinueLoop, Gene, ObjInst, Return, SeqObj, Stress



class IStmt:

    def exec_block(self, env, stmts):
        for s in stmts:
            self.exec_stmt(env, s)

    def exec_stmt(self, env, s):
        self.tick()
        k = s[0]
        if k == "typealias": return self._ex_typealias()
        if k == "block": return self._ex_block(env, s)
        elif k == "const": return self._ex_const(env, s)
        elif k == "let": return self._ex_let(env, s)
        elif k == "letann": return self._ex_letann(env, s)
        elif k == "letpat": return self._ex_letpat(env, s)
        elif k == "forpat": return self._ex_forpat(env, s)
        elif k == "multi": return self._ex_multi(env, s)
        elif k == "assign": return self._ex_assign(env, s)
        elif k == "idx_assign": return self._ex_idx_assign(env, s)
        elif k == "mem_assign": return self._ex_mem_assign(env, s)
        elif k == "if": return self._ex_if(env, s)
        elif k == "while": return self._ex_while(env, s)
        elif k == "loop": return self._ex_loop(env, s)
        elif k == "scope": return self._ex_scope(env, s)
        elif k == "for": return self._ex_for(env, s)
        elif k == "return": return self._ex_return(env, s)
        elif k == "break": return self._ex_break()
        elif k == "continue": return self._ex_continue()
        elif k == "expr": return self._ex_expr(env, s)
        elif k == "match": return self._ex_match(env, s)
        elif k == "use": return self._ex_use(env, os, s)
        elif k == "module": return self._ex_module(contextlib, env, s)
        elif k == "raise": return self._ex_raise(env, s)
        elif k == "stress": return self._ex_stress(env, s)
        elif k == "gene": return self._ex_gene(env, s)
        elif k == "pheno": return self._ex_pheno(s)
        elif k == "trait": return self._ex_trait(s)
        elif k == "yield": return self._ex_yield(env, s)
        elif k == "splice": return self._ex_splice(env, s)
        elif k == "silence": return self._ex_silence(s)
        elif k == "operon": return self._ex_operon(s)
        elif k == "enhance": return self._ex_enhance(s)
        elif k == "ires": return self._ex_ires(s)
        elif k == "fate": return self._ex_fate(s)
        elif k == "regulate": return self._ex_regulate(s)
        elif k == "ligand": return self._ex_ligand(s)
        elif k == "autoinducer": return self._ex_autoinducer(s)
        elif k == "decoy": return self._ex_decoy(s)
        elif k == "toggle": return self._ex_toggle(s)
        elif k == "repressilator": return self._ex_repressilator(s)
        elif k in ("frame", "edit", "anchor_export", "anchor_import"): return self._ex_frame()
        elif k == "tad": return self._ex_tad(env, s)

    def _ex_typealias(self, ):
        # W01-s2: a type-alias declaration is parse-time metadata; the
        # runtime is inert (mirror of interp.rs Stmt::TypeAlias law).
        return

    def _ex_block(self, env, s):
        self.exec_block(self.new_scope(env), s[1])

    def _ex_const(self, env, s):
        # W05: immutable binding, deep-freeze + const name marker.
        _, name, ex = s
        v = self.eval_expr(env, ex)
        if name in env:
            self.note(4, f"rebinding '{name}'")
        self.deep_freeze(v)
        env[name] = v
        env[("__const__", name)] = True

    def _ex_let(self, env, s):
        v = self.eval_expr(env, s[2])
        if s[1] in env:
            self.note(4, f"rebinding '{s[1]}'")
        env[s[1]] = v

    def _ex_letann(self, env, s):
        # W01 (L2c): annotated definition, mismatch = catchable unfolded
        # Stress; the binding does NOT happen (mirror of interp.rs).
        _, name, ann, ex = s
        v = self.eval_expr(env, ex)
        if not ann_matches(v, ann):
            raise Stress("unfolded", f"type annotation violated: '{name}' expects {ann_render(ann)}, got {type_name(v)}")
        if name in env:
            self.note(4, f"rebinding '{name}'")
        env[name] = v

    def _ex_letpat(self, env, s):
        # L1a: destructuring definition
        v = self.eval_expr(env, s[2])
        self.bind_pattern(env, s[1], v)

    def _ex_forpat(self, env, s):
        # L1a: destructuring loop
        _, pat, it, body = s
        itv = self.eval_expr(env, it)
        if isinstance(itv, SeqObj):
            while True:
                self.tick()
                item = itv.pull()
                if item is None:
                    break
                child = self.new_scope(env)
                self.bind_pattern(child, pat, item)
                try:
                    self.exec_block(child, body)
                except BreakLoop:
                    break
                except ContinueLoop:
                    continue
                except Return as r:
                    raise r
            return
        if isinstance(itv, list):
            items = list(itv)
        elif isinstance(itv, str):
            items = list(itv)
        elif isinstance(itv, bytes):
            # W029 mirror: iterating bytes yields ints 0..=255
            items = list(itv)
        elif isinstance(itv, dict):
            # #214: iteration yields BOTH stores' keys (side order after
            # dict order — the documented mixed-map order deviation)
            items = _map_keys(itv)
        else:
            self.note(4, f"cannot iterate {type_name(itv)}; loop skipped")
            items = []
        for item in items:
            self.tick()
            child = self.new_scope(env)
            self.bind_pattern(child, pat, item)
            try:
                self.exec_block(child, body)
            except BreakLoop:
                break
            except ContinueLoop:
                continue
            except Return as r:
                raise r

    def _ex_multi(self, env, s):
        # L1a: multiple assignment / swap, all values evaluated first
        _, targets, values, define = s
        if not define:
            # W05: rebinding a const name stresses before any write
            for t in targets:
                if t[0] == "ident" and self.is_const(env, t[1]):
                    raise Stress("frozen", f"cannot reassign const '{t[1]}'")
        vals = [self.eval_expr(env, v) for v in values]
        if len(vals) < len(targets):
            self.note(4, "multi-assign: fewer values than targets; the rest bind null")
        elif len(vals) > len(targets):
            self.note(4, "multi-assign: extra values dropped")
        for i, t in enumerate(targets):
            val = vals[i] if i < len(vals) else None
            if define:
                if t[0] == "ident":
                    name = t[1]
                    if name in env:
                        self.note(4, f"rebinding '{name}'")
                    env[name] = val
                else:
                    self.note(4, "multi 'let' target must be a name; dropped")
            else:
                if t[0] == "ident":
                    name = t[1]
                    target = self.find_env(env, name)
                    if target is None:
                        self.note(4, f"'{name}' was not declared; auto-declared")
                    self.assign(env, name, val)
                elif t[0] == "index":
                    self.cur_line = t[3] if len(t) > 3 else 0  # W07 mirror: assign-target stamp
                    tv = self.eval_expr(env, t[1])
                    iv = self.eval_expr(env, t[2])
                    if isinstance(tv, list):
                        if self.is_frozen(tv):
                            raise self._frozen_stress("list")
                        try:
                            idx = self.as_index(iv, len(tv))
                        except Stress:
                            idx = None
                        if idx is not None and idx < len(tv):
                            tv[idx] = val
                        else:
                            tv.append(val)
                            self.note(4, "index out of range; value appended")
                    elif isinstance(tv, dict):
                        if self.is_frozen(tv):
                            raise self._frozen_stress("map")
                        # #214: container keys key by VALUE (side store)
                        _map_insert_key(tv, iv, val)
                    else:
                        self.note(4, "index assignment on non-container ignored")
                elif t[0] == "member":
                    tv = self.eval_expr(env, t[1])
                    if isinstance(tv, ObjInst):
                        tv.fields[t[2]] = val
                    elif isinstance(tv, dict):
                        if self.is_frozen(tv):
                            raise self._frozen_stress("map")
                        tv[t[2]] = val
                    else:
                        self.note(4, "member assignment on non-map ignored")
                else:
                    self.note(4, "multi-assign target invalid; value dropped")

    def _ex_assign(self, env, s):
        _, name, op, ve = s
        v = self.eval_expr(env, ve)
        if self.is_const(env, name):
            raise Stress("frozen", f"cannot reassign const '{name}'")
        target = self.find_env(env, name)
        if op is None:
            if target is None:
                self.note(4, f"'{name}' was not declared; auto-declared")
            self.assign(env, name, v)
        else:
            cur = self.lookup(env, name) if target is not None else None
            nv = self.binop(op, cur, v)
            if not self.assign(env, name, nv):
                self.note(4, f"'{name}' was not declared; auto-declared")

    def _ex_idx_assign(self, env, s):
        _, te, ie, op, ve = s
        # Z-512-CAP-PARITY mirror leg: the W07 cur_line RESET here zeroed
        # the stale carryover line the engine renders (nothing else in
        # the statement consumes cur_line) — removed; the full
        # differential corpus proves the removal inert.
        tv = self.eval_expr(env, te)
        iv = self.eval_expr(env, ie)
        v = self.eval_expr(env, ve)
        if isinstance(tv, list):
            if self.is_frozen(tv):
                raise self._frozen_stress("list")
            try:
                idx = self.as_index(iv, len(tv))
            except Stress:
                idx = None
            cur = tv[idx] if (idx is not None and idx < len(tv)) else None
            nv = self.binop(op, cur, v) if op else v
            self._cycle_note_insert(tv, nv)  # W013: before the edge lands
            if idx is not None and idx < len(tv):
                tv[idx] = nv
            else:
                tv.append(nv)
                self.note(4, "index out of range; value appended")
        elif isinstance(tv, dict):
            if self.is_frozen(tv):
                raise self._frozen_stress("map")
            cur = _map_lookup(tv, iv)
            if cur is _MAP_MISS:
                cur = None
            nv = self.binop(op, cur, v) if op else v
            # pheno_equality pin: instance keys store AS INSTANCES (the
            # Rust core keys maps by the actual value; v_display here
            # stringified them into "<phenotype P>", found by the
            # builder-B parity-finding resolution differential).
            # ObjInst is hashable (id-based), so dict storage works.
            # #214: container keys (list/map) now key by VALUE via the
            # side pair-list — the write-only-key display-text path is
            # retired; equality is the deep_eq seen-pair law, exact.
            # W029 mirror: bytes are scalar keys (native hashable, exact).
            self._cycle_note_insert(tv, nv)  # W013: value edge (keys not walked)
            _map_insert_key(tv, iv, nv)
        else:
            self.note(4, "index assignment on non-container ignored")

    def _ex_mem_assign(self, env, s):
        _, te, key, op, ve = s
        tv = self.eval_expr(env, te)
        v = self.eval_expr(env, ve)
        if isinstance(tv, ObjInst):
            cur = tv.fields.get(key)
            nv = self.binop(op, cur, v) if op else v
            self._cycle_note_insert(tv.fields, nv)  # W013: before the edge lands
            tv.fields[key] = nv
        elif isinstance(tv, dict):
            if self.is_frozen(tv):
                raise self._frozen_stress("map")
            # Z-MAPORDER: member-style read (HEAD then TAIL) for the
            # op-accumulator, and the write routes through the store
            # insert (a brand-new string member of a promoted map must
            # land in the TAIL, not the frozen HEAD)
            cur = _map_member_get(tv, key)
            if cur is _MAP_MISS:
                cur = None
            nv = self.binop(op, cur, v) if op else v
            self._cycle_note_insert(tv, nv)  # W013: before the edge lands
            _map_insert_key(tv, key, nv)
        else:
            self.note(4, "member assignment on non-map ignored")

    def _ex_if(self, env, s):
        _, branches, els = s
        for cond, body in branches:
            if truthy(self.eval_expr(env, cond)):
                self.exec_block(self.new_scope(env), body)
                return
        if els is not None:
            self.exec_block(self.new_scope(env), els)

    def _ex_while(self, env, s):
        _, cond, body = s
        while truthy(self.eval_expr(env, cond)):
            self.tick()
            try:
                self.exec_block(self.new_scope(env), body)
            except BreakLoop:
                break
            except ContinueLoop:
                continue
            except Return as r:
                raise r

    def _ex_loop(self, env, s):
        _, body = s
        while True:
            self.tick()
            try:
                self.exec_block(self.new_scope(env), body)
            except BreakLoop:
                break
            except ContinueLoop:
                continue
            except Return as r:
                raise r

    def _ex_scope(self, env, s):
        # W17: tasks spawned inside register on this scope and are
        # reaped at block exit on every flow path. cancel-on-error
        # (default on) asks the children to stop before reaping when
        # the block unwinds by stress; the stress still propagates.
        _, body = s
        if not hasattr(self, "scope_stack"):
            self.scope_stack = []
        self.scope_stack.append([])
        err = None
        try:
            self.exec_block(self.new_scope(env), body)
        except BreakLoop as b:
            err = b
        except ContinueLoop as c:
            err = c
        except Return as r:
            err = r
        except Stress as st:
            err = st
        ids = self.scope_stack.pop()
        cancel_on_err = self.cell.get("scope.cancel_on_error") != "off"
        if isinstance(err, Stress) and cancel_on_err:
            # #59: the reap cancel is MECHANICAL containment, not a user
            # action — it narrates NOTHING on either engine. The Rust
            # lanes cancel real workers here and cancel-vs-finish is a
            # true thread race (the qemu legs flipped the note text
            # between the tree-walk and VM modes); the sequential engine
            # has nothing live to cancel (children are born finished).
            # The join below is the observable signal; explicit cancel()
            # keeps its documented notes.
            pass
        for i in ids:
            self.builtin(env, "join", [i])
        if err is not None:
            raise err

    def _ex_for(self, env, s):
        _, name, it, body = s
        itv = self.eval_expr(env, it)
        items = []
        if isinstance(itv, SeqObj):
            while True:
                self.tick()
                item = itv.pull()
                if item is None:
                    break
                child = self.new_scope(env)
                child[name] = item
                try:
                    self.exec_block(child, body)
                except BreakLoop:
                    break
                except ContinueLoop:
                    continue
                except Return as r:
                    raise r
            return
        if isinstance(itv, list):
            items = list(itv)
        elif isinstance(itv, str):
            items = list(itv)
        elif isinstance(itv, bytes):
            # W029 mirror: iterating bytes yields ints 0..=255
            items = list(itv)
        elif isinstance(itv, dict):
            items = _map_keys(itv)
        else:
            self.note(4, f"cannot iterate {type_name(itv)}; loop skipped")
        for item in items:
            self.tick()
            child = self.new_scope(env)
            child[name] = item
            try:
                self.exec_block(child, body)
            except BreakLoop:
                break
            except ContinueLoop:
                continue
            except Return as r:
                raise r

    def _ex_return(self, env, s):
        raise Return(self.eval_expr(env, s[1]))

    def _ex_break(self, ):
        raise BreakLoop()

    def _ex_continue(self, ):
        raise ContinueLoop()

    def _ex_expr(self, env, s):
        self.eval_expr(env, s[1])  # propagates: stress frames or top-level contain

    def _ex_match(self, env, s):
        _, subj, cases = s
        sv = self.eval_expr(env, subj)
        for pat, body in cases:
            # W02 (match-v2): one binding dict per arm; captures live only
            # in the arm that hits (mirror of interp.rs Stmt::Match).
            bindings = {}
            if self.match_pat(env, bindings, sv, pat):
                child = self.new_scope(env)
                child.update(bindings)
                self.exec_block(child, body)
                return

    def _ex_use(self, env, os, s):
        # W025 stage 2: a trailing `/*` marks the WILDCARD form, flat-bind
        # the target table's exports without binding the module map itself
        # (an explicit `as` alias still binds it). Resolution stays
        # FILE-FIRST: the full path is tried as a file, then each shorter
        # prefix is loaded as a file and the remaining segments descend
        # the exported nested-module tables, longest prefix first (mirror
        # of interp.rs Stmt::Use + descend_tables, SPEC §8).
        path = s[1]
        wildcard = path.endswith("/*")
        base = path[:-2] if wildcard else path
        modv = self.load_module(base)
        if modv is None:
            segs = base.split("/")
            for kk in range(len(segs) - 1, 0, -1):
                rootv = self.load_module("/".join(segs[:kk]))
                if rootv is None:
                    continue
                table = rootv
                hit = True
                for seg in segs[kk:]:
                    nxt = table.get(seg) if isinstance(table, dict) else None
                    if nxt is None:
                        self.note(4, f"use '{path}': segment '{seg}' is not a nested module table; import binds nothing")
                        hit = False
                        break
                    table = nxt
                if hit:
                    modv = table
                    break
        name = s[2] or os.path.basename(base.replace("\\", "/")).split(".")[0].split("/")[-1]
        if not wildcard or s[2]:
            env[name] = modv if modv is not None else {}
        # flat-bind ALL exports beside the alias map (genes AND data);
        # for the wildcard form this flat bind IS the whole import
        if isinstance(modv, dict):
            for kname, v in modv.items():
                env[kname] = v

    def _ex_module(self, contextlib, env, s):
        # W025 stage 2: nested sub-module table (mirror of interp.rs
        # Stmt::Module). The body runs ONCE here in a fresh child scope;
        # stress propagates to the enclosing containment exactly like a
        # module-file top-level statement, flow signals end only their
        # own statement. The child scope's own names become the export
        # table, sorted like the file-module loader sorts them, so both
        # engines print and flat-bind identically. Last declaration wins.
        _, mname, mbody = s
        child = self.new_scope(env)
        for st in mbody:
            # flow signals end only their own statement (see block above)
            with contextlib.suppress(Return, BreakLoop, ContinueLoop):
                self.exec_stmt(child, st)
        exports = {kk: vv for kk, vv in child.items()
                   if isinstance(kk, str) and kk != "__parent__" and not kk.startswith("#")}
        env[mname] = {kk: exports[kk] for kk in sorted(exports)}

    def _ex_raise(self, env, s):
        msg = self.eval_expr(env, s[2])
        raise Stress(s[1] or "unfolded", v_display(msg))

    def _ex_stress(self, env, s):
        _, kind, body, rescue = s
        try:
            self.exec_block(env, body)
        except Stress as st:
            # W06 (D-014) mirror: propagation is a RETURN, not a failure,
            # it crosses stress/rescue boundaries on its way to the gene
            # boundary. Pre-arms BEFORE kind matching so rescue (including
            # `rescue any`) can never contain or spoof it.
            if st.prop is not None:
                raise Return(st.prop)
            if kind is not None and kind != st.kind and kind != "any":
                raise st
            if rescue is not None:
                bind, rbody = rescue
                child = self.new_scope(env)
                if bind:
                    child[bind] = st.as_map()
                self.exec_block(child, rbody)
            else:
                self.note(4, f"stress contained: [{st.kind}] {st.message}")

    def _ex_gene(self, env, s):
        g = s[1]
        name = g.name or "<lambda>"
        # T2b graded methylation (D-005): mirror of the Rust core
        if g.methylate:
            self.methyl_levels[name] = self.methyl_levels.get(name, 0) + 1
        elif g.acetylate:
            self.methyl_levels[name] = max(0, self.methyl_levels.get(name, 0) - 1)
        # reg-bio-3 (B3): executed @m6a defs deepen the site-density level
        if g.m6a:
            self.m6a_levels[name] = min(self.m6a_levels.get(name, 0) + 1, 3)
        # reg-bio-3 (C10): gene dosage registry
        if g.copies > 1:
            self.copies[name] = g.copies
        else:
            self.copies.pop(name, None)
        # @m6a-stabilized transcripts win dispatch among same-name candidates
        # (reg-bio-3 (B3): resistance reads the quantitative level >= 1)
        if not g.m6a and self.m6a_levels.get(name, 0) >= 1:
            self.note(4, f"'{name}' is @m6a-stabilized; redefinition ignored (mark the new copy to replace it)")
            return
        if g.name and g.name not in self.defined_genes:
            self.defined_genes.append(g.name)
        # P6-wave fix (loop-capture pin): the closure rides the VALUE,
        # not the shared AST node — the Rust core pairs the def with the
        # definition env at value creation (Value::Gene(def, env)), so
        # two executions of the same syntactic gene inside a loop
        # capture DIFFERENT iteration envs. Mutating g.closure made
        # every instance share the last definition env (cap:2,2,2
        # vs the core's 0,1,2). Shallow copy: body/params stay shared,
        # closure becomes per-instance.
        inst = copy.copy(g)
        inst.closure = env
        env[inst.name or "<lambda>"] = inst

    def _ex_pheno(self, s):
        p = s[1]
        self.phenos[p.name] = p

    def _ex_trait(self, s):
        # W04: registry, last declaration wins (redefinition noted)
        t = s[1]
        if t.name in self.traits:
            self.note(4, f"redefining trait '{t.name}'")
        self.traits[t.name] = t

    def _ex_yield(self, env, s):
        v = self.eval_expr(env, s[1]) if s[1] is not None else None
        if self.seq_buffer is not None:
            self.seq_buffer.append(v)
        else:
            self.note(4, "yield outside a sequence; treated as return")
            raise Return(v)

    def _ex_splice(self, env, s):
        _, root, variants = s
        # loop-9 (F-4): registry for runtime splice_shift re-resolution
        self.splice_registry[root] = s
        chosen = self.choose_variant(root, variants)
        if chosen:
            vname, vparams, body, vmarks, vline = chosen
            self.note(1, f"splice '{root}' → variant '{vname}' active")
            g = Gene(root, vparams, None, body,
                     ac="acetylate" in vmarks, me="methylate" in vmarks, m6="m6a" in vmarks, line=vline)
            if root not in self.defined_genes:
                self.defined_genes.append(root)
            env[root] = g

    def _ex_silence(self, s):
        _, sfrm, sto, sstr, ssites = s
        self.silences.append((sfrm, sto, sstr, ssites))
        if sstr < 1.0 or ssites > 1:
            suffix = f" (strength {sstr!r}, sites {ssites})"
        else:
            suffix = ""
        if sto:
            self.note(1, f"RISC loaded: '{sfrm}' silenced → '{sto}'{suffix}")
        else:
            # reg-bio (F-4): pure RISC degradation (was a silent no-op)
            self.note(1, f"RISC loaded: '{sfrm}' degraded (no replacement){suffix}")

    def _ex_operon(self, s):
        # reg-bio-3 (A1/A7): register the unit (membership by name,
        # last-wins redefinition, cross-unit ownership ignored) (mirror)
        _, oname, omembers = s
        if not omembers:
            self.note(4, f"operon '{oname}': no cistrons declared; skipped")
        else:
            self.operons = [u for u in self.operons if u["name"] != oname]
            unit = {"name": oname, "members": [], "transcripts": 0}
            for og, orbs in omembers:
                if any(om == og for u2 in self.operons for om, _o in u2["members"]):
                    self.note(4, f"cistron '{og}' already belongs to another operon; ignored")
                    continue
                unit["members"].append((og, orbs))
            if not unit["members"]:
                self.note(4, f"operon '{oname}': every cistron belonged to another unit; skipped")
            else:
                self.operons.append(unit)
                self.note(1, f"operon '{oname}': {len(unit['members'])} cistron(s) on one transcript")

    def _ex_enhance(self, s):
        for n in s[1]:
            if n not in self.enhanced:
                self.enhanced.append(n)

    def _ex_ires(self, s):
        if s[1] not in self.ires:
            self.ires.append(s[1])

    def _ex_fate(self, s):
        self.fates[s[1]] = (s[2], s[3])

    def _ex_regulate(self, s):
        self.grn_edges.extend(s[1])
        self.trans_edges.extend(s[2])
        self.grn_binds.extend(s[3])

    def _ex_ligand(self, s):
        if s[1] not in self.ligands:
            self.ligands.append(s[1])

    def _ex_autoinducer(self, s):
        # loop-9 (C8): register a quorum-sensing signal species (mirror)
        self._signal_register(s[1])

    def _ex_decoy(self, s):
        self.decoys.append((s[1], s[2], s[3]))

    def _ex_toggle(self, s):
        self.toggles.append((s[1], s[2], True))

    def _ex_repressilator(self, s):
        self.repressi_ring = s[1]
        self.repressi_i = 0
        self.repressi_tick = 0
        # reg-bio (F-5): inline kinetics layer onto the current params
        for _fk in ("alpha", "gamma", "hill", "basal", "noise", "seed"):
            if s[3][_fk] is not None:
                self.repressi_params[_fk] = s[3][_fk]

    def _ex_frame(self, ):
        pass

    def _ex_tad(self, env, s):
        self.exec_block(env, s[2])

