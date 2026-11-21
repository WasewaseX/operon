"""operon oracle: interp.pat (split of bootstrap/oracle.py)."""

from ..annot import type_name
from ..fmt import truthy
from ..mapops import _MAP_MISS, _map_member_get, deep_eq
from ..values import Stress, Variant



class IPat:

    # ---- statements
    def bind_pattern(self, env, pat, v):
        # L1a: destructuring binder, soft-miss semantics (Total Grammar)
        k = pat[0]
        if k == "pbind":
            name = pat[1]
            if name in env:
                self.note(4, f"rebinding '{name}'")
            env[name] = v
        elif k == "plist":
            elems, rest = pat[1], pat[2]
            if isinstance(v, list):
                n = len(v)
                for i, ep in enumerate(elems):
                    if i < n:
                        self.bind_pattern(env, ep, v[i])
                    else:
                        self.note(4, f"destructure: index {i} missing; null")
                        self.bind_pattern(env, ep, None)
                if rest is not None:
                    tail = list(v[len(elems):]) if len(elems) < n else []
                    if rest in env:
                        self.note(4, f"rebinding '{rest}'")
                    env[rest] = tail
                elif n > len(elems):
                    self.note(4, f"destructure: {n - len(elems)} extra element(s) dropped")
            elif isinstance(v, str):
                # list patterns destructure strings by char (like for-in)
                chars = list(v)
                n = len(chars)
                for i, ep in enumerate(elems):
                    if i < n:
                        self.bind_pattern(env, ep, chars[i])
                    else:
                        self.note(4, f"destructure: index {i} missing; null")
                        self.bind_pattern(env, ep, None)
                if rest is not None:
                    tail = chars[len(elems):] if len(elems) < n else []
                    if rest in env:
                        self.note(4, f"rebinding '{rest}'")
                    env[rest] = tail
                elif n > len(elems):
                    self.note(4, f"destructure: {n - len(elems)} extra element(s) dropped")
            elif v is None:
                self.note(4, "destructure of null binds nulls")
                for ep in elems:
                    self.bind_pattern(env, ep, None)
                if rest is not None:
                    if rest in env:
                        self.note(4, f"rebinding '{rest}'")
                    env[rest] = []
            else:
                self.note(4, f"cannot destructure {type_name(v)}; pattern binds nulls")
                for ep in elems:
                    self.bind_pattern(env, ep, None)
                if rest is not None:
                    if rest in env:
                        self.note(4, f"rebinding '{rest}'")
                    env[rest] = []
        elif k == "pmap":
            keys = pat[1]
            if isinstance(v, dict):
                for key in keys:
                    # Z-MAPORDER: member-style probe — dict HEAD then side
                    # TAIL (a post-promotion string key lives in the tail)
                    hit = _map_member_get(v, key)
                    if hit is not _MAP_MISS:
                        if key in env:
                            self.note(4, f"rebinding '{key}'")
                        env[key] = hit
                    else:
                        self.note(4, f"destructure: key '{key}' missing; null")
                        if key in env:
                            self.note(4, f"rebinding '{key}'")
                        env[key] = None
            else:
                self.note(4, f"cannot destructure {type_name(v)}; pattern binds nulls")
                for key in keys:
                    if key in env:
                        self.note(4, f"rebinding '{key}'")
                    env[key] = None

    # ------------------------------------------------------------- W02 match-v2
    def eval_pat_val(self, env, l):
        """Mirror of the Rust pattern-literal eval: `?!` propagation is a
        return (never contained); any other stress becomes a note + null."""
        try:
            return self.eval_expr(env, l)
        except Stress as st:
            if st.prop is not None:
                raise
            self.note(4, f"pattern evaluation contained: [{st.kind}] {st.message}")
            return None

    def match_pat(self, env, bindings, sv, pat):
        """W02 (match-v2) recursive pattern matcher, op-for-op mirror of
        interp.rs match_pat. Total Grammar: a pattern never hard-fails; a
        non-matching shape simply misses; only `?!` propagation escapes."""
        k = pat[0]
        if k == "wild":
            return True
        if k == "bind":
            bindings[pat[1]] = sv
            return True
        if k == "lit":
            # literal evals in the arm scope so same-arm bindings are visible
            gev = self.new_scope(env)
            gev.update(bindings)
            return deep_eq(sv, self.eval_pat_val(gev, pat))
        if k == "null":
            return deep_eq(sv, None)
        if k == "multi":
            # legacy literal comma-run, any literal hits (first wins)
            gev = self.new_scope(env)
            gev.update(bindings)
            for lt in pat[1]:
                if deep_eq(sv, self.eval_pat_val(gev, lt)):
                    return True
            return False
        if k == "or":
            # alternatives in order, first hit binds; a failed alternative's
            # partial captures never leak (scratch dict, lifted on hit)
            for alt in pat[1]:
                scratch = {}
                if self.match_pat(env, scratch, sv, alt):
                    bindings.update(scratch)
                    return True
            return False
        if k == "variant":
            _, tag, payload = pat
            if isinstance(sv, Variant) and sv.tag == tag:
                if payload is None:
                    return True  # tag-only form
                if sv.payload is None:
                    return False  # payload pattern vs payload-less value
                return self.match_pat(env, bindings, sv.payload, payload)
            return False
        if k == "list":
            _, elems, rest = pat
            if not isinstance(sv, list):
                return False
            if rest is None:
                if len(sv) != len(elems):
                    return False
            elif len(sv) < len(elems):
                return False
            for i, ep in enumerate(elems):
                if not self.match_pat(env, bindings, sv[i], ep):
                    return False
            if rest is not None:
                bindings[rest] = sv[len(elems):]
            return True
        if k == "map":
            _, keys = pat
            if not isinstance(sv, dict):
                return False
            for key, sub in keys:
                # Z-MAPORDER: member-style probe (dict HEAD then side TAIL)
                hit = _map_member_get(sv, key)
                if hit is _MAP_MISS:
                    return False
                if sub is None:
                    bindings[key] = hit
                elif not self.match_pat(env, bindings, hit, sub):
                    return False
            return True
        if k == "guard":
            _, p, cond = pat
            if not self.match_pat(env, bindings, sv, p):
                return False
            gev = self.new_scope(env)
            gev.update(bindings)
            try:
                return truthy(self.eval_expr(gev, cond))
            except Stress as st:
                if st.prop is not None:
                    raise  # W06: propagation is a return, never a failure
                self.note(4, f"pattern guard contained: [{st.kind}] {st.message}")
                return False
        return False
