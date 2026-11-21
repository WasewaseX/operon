"""operon oracle: interp.eval (split of bootstrap/oracle.py)."""

import copy
from ..annot import type_name
from ..fmt import truthy, v_display
from ..mapops import _MAP_MISS, _NON_SCALAR_SCAN_CAP, _is_container_key, _map_insert_key, _map_items, _map_keys, _map_member_get, deep_eq
from ..values import ObjInst, SeqObj, Stress, Variant



class IEval:

    def choose_variant(self, root, variants):
        if not variants:
            return None
        cv = self.cell.get(f"variant.{root}")
        if cv:
            for vn, vp, b, mk, vl in variants:
                if vn == cv:
                    return (vn, vp, b, mk, vl)
        cv = self.cell.get("cli.variant")
        if cv:
            for vn, vp, b, mk, vl in variants:
                if vn == cv:
                    return (vn, vp, b, mk, vl)
        # 3. loop-9 (F-4): runtime splice_shift (a bound splicing factor
        # overrides the static mark; the operator pins above override it)
        sv = self.splice_shift.get(root)
        if sv:
            for vn, vp, b, mk, vl in variants:
                if vn == sv:
                    return (vn, vp, b, mk, vl)
        # 4. m6a-marked variant (T2c: mirrors the Rust core)
        for vn, vp, b, mk, vl in variants:
            if "m6a" in mk:
                return (vn, vp, b, mk, vl)
        # 5. first declared
        return variants[0]

    # ---- expressions
    def member_value(self, tv, key):
        # L1a: shared member read for `.` and `?.` (safe form pre-checks Null)
        if isinstance(tv, ObjInst):
            if key in tv.fields:
                return tv.fields[key]
            self.note(4, f"field '{key}' missing on phenotype {tv.defn.name}; null")
            return None
        if isinstance(tv, dict):
            # Z-MAPORDER: dict HEAD probe first (C-speed, unique hit), then
            # the side TAIL — a post-promotion string member lives there
            hit = _map_member_get(tv, key)
            if hit is not _MAP_MISS:
                return hit
            self.note(4, f"member '{key}' missing on map; null")
            return None
        self.note(4, f"member '{key}' on {type_name(tv)} is null")
        return None

    def eval_expr(self, env, e):
        self.tick()
        k = e[0]
        if k == "lit" or k == "null":
            return None if k == "null" else e[1]
        if k == "interp":
            out = []
            for pk, pv in e[1]:
                if pk == "lit":
                    out.append(pv)
                else:
                    out.append(v_display(self.eval_expr(env, pv)))
            return "".join(out)
        if k == "list":
            return [self.eval_expr(env, x) for x in e[1]]
        if k == "map":
            m = {}
            for ke, ve in e[1]:
                kv = self.eval_expr(env, ke)
                # W029 mirror: bytes are scalar keys (Rust key_scalar includes
                # Bytes), never stringified
                val = self.eval_expr(env, ve)
                # #214: container keys key by VALUE (side pair-list), the
                # Rust MapStore law — no more display-text canonicalization
                _map_insert_key(m, kv, val)
            return m
        if k == "ident":
            v = self.lookup(env, e[1])
            if v is not None or e[1] in env or self.find_env(env, e[1]) is not None:
                return v
            self.note(4, f"unbound '{e[1]}' read as null")
            return None
        if k == "un":
            v = self.eval_expr(env, e[2])
            if e[1] == "neg":
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    if isinstance(v, int) and v == -(2**63):
                        raise Stress("overflow", "int overflow in negation (i64::MIN)")
                    return -v
                raise Stress("unfolded", f"cannot negate {type_name(v)}")
            if e[1] == "bitnot":
                if isinstance(v, bool):
                    return ~int(v)
                if isinstance(v, int):
                    return ~v
                raise Stress("unfolded", f"cannot bit-invert {type_name(v)}")
            return not truthy(v)
        if k == "tern":
            _, cond, a, b = e
            return self.eval_expr(env, a) if truthy(self.eval_expr(env, cond)) else self.eval_expr(env, b)
        if k == "prop":
            # W06 (D-014) mirror: `e?!`, Some/Ok unwrap to the payload;
            # None/Err unwind to the nearest enclosing gene boundary (the
            # gene RETURNS the variant). Plain values pass through untouched
            # (silent identity, the same contract as `?.` on non-null).
            _, sub, line = e
            v = self.eval_expr(env, sub)
            if isinstance(v, Variant):
                if v.tag in ("Some", "Ok"):
                    # null payload is a REAL payload: ok(null) stores Some(Null)
                    # on the Rust side, so `?!` unwraps to null (W06 parity fix,
                    # found by the std_serialize proof, the old `payload is
                    # not None` guard wrongly unwound on Ok(null)/Some(null))
                    return v.payload
                sig = Stress("propagate", "")
                sig.prop = v
                sig.line = line
                raise sig
            return v
        if k == "new":
            _, name, args_e = e
            p = self.phenos.get(name)
            if p is None:
                self.note(4, f"phenotype '{name}' not declared; instance is an empty map")
                return {}
            args = [self.eval_expr(env, a) for a in args_e]
            # z-s2-harden (#126.7): the new-site env rides into construction
            # so field initializers evaluate where the instance is born
            return self.construct_obj(p, args, env)
        if k == "bin":
            self.cur_line = e[4] if len(e) > 4 else 0  # W07 mirror: dx-r4 stamp
            op = e[1]
            if op == "and":
                lv = self.eval_expr(env, e[2])
                return self.eval_expr(env, e[3]) if truthy(lv) else lv
            if op == "or":
                lv = self.eval_expr(env, e[2])
                return lv if truthy(lv) else self.eval_expr(env, e[3])
            if op == "nullish":
                # L1a: coalesce Null only, falsy non-null passes through
                lv = self.eval_expr(env, e[2])
                return self.eval_expr(env, e[3]) if lv is None else lv
            lv = self.eval_expr(env, e[2])
            rv = self.eval_expr(env, e[3])
            return self.binop(op, lv, rv)
        if k == "call":
            self.cur_line = e[3] if len(e) > 3 else 0  # W07 mirror: A13 stamp
            if e[1][0] == "ident":
                # Z-116 (#116 leg 3): the RISC gate runs BEFORE the args
                # evaluate ("a degraded call is not expression" — the Rust
                # tree-walk order; the VM gates pre-args via CallGateRisc).
                # Degrade returns null without evaluating anything; redirect
                # evaluates the args and calls the replacement.
                dec = self.risc_gate(env, e[1][1])
                if dec == "degrade":
                    return None
                if isinstance(dec, tuple):  # ("redirect", target_name)
                    to = dec[1]
                    tgt = self.lookup(env, to)
                    argvs = [self.eval_expr(env, a) for a in e[2]]
                    return self.call_value(env, tgt, argvs)
                args = [self.eval_expr(env, a) for a in e[2]]
                return self.call_named(env, e[1][1], args, _risc_pre=True)
            callee = self.eval_expr(env, e[1])
            args = [self.eval_expr(env, a) for a in e[2]]
            return self.call_value(env, callee, args)
        if k == "index":
            self.cur_line = e[3] if len(e) > 3 else 0  # W07 mirror: dx-r4 stamp
            tv = self.eval_expr(env, e[1])
            iv = self.eval_expr(env, e[2])
            if isinstance(tv, list):
                idx = self.as_index(iv, len(tv))
                if idx < len(tv):
                    return tv[idx]
                raise Stress("missing", f"index {idx} out of range")
            if isinstance(tv, dict):
                # Z-512-CAP-PARITY: a container-key probe scans only the
                # first 512 UNIFIED items (the engine's position() KC_OTHER
                # arm .take(NON_SCALAR_SCAN_CAP), SPEC §763 "treated as
                # absent") — a match beyond the cap stresses "missing"
                # exactly like a genuinely absent key. Scalar probes and
                # the int/float cross-equality class stay UNBOUNDED
                # (position_h's uncapped scalar arms).
                if _is_container_key(iv):
                    n = 0
                    for kk, vv in _map_items(tv):
                        if n >= _NON_SCALAR_SCAN_CAP:
                            break
                        n += 1
                        if deep_eq(kk, iv):
                            return vv
                else:
                    for kk, vv in _map_items(tv):
                        if deep_eq(kk, iv):
                            return vv
                raise Stress("missing", "key not found")
            if isinstance(tv, str):
                idx = self.as_index(iv, len(tv))
                if idx < len(tv):
                    return tv[idx]
                raise Stress("missing", "char index out of range")
            # W029 mirror: bytes[i] -> int (Python parity)
            if isinstance(tv, bytes):
                idx = self.as_index(iv, len(tv))
                if idx < len(tv):
                    return tv[idx]
                raise Stress("missing", "byte index out of range")
            raise Stress("unfolded", f"cannot index {type_name(tv)}")
        if k == "member":
            tv = self.eval_expr(env, e[1])
            return self.member_value(tv, e[2])
        if k == "member?":
            # L1a: optional chaining, Null receiver is Null, silently
            tv = self.eval_expr(env, e[1])
            if tv is None:
                return None
            return self.member_value(tv, e[2])
        if k == "method?":
            tv = self.eval_expr(env, e[1])
            if tv is None:
                return None
            args = [self.eval_expr(env, a) for a in e[3]]
            return self.call_method(env, tv, e[2], args)
        if k == "method":
            tv = self.eval_expr(env, e[1])
            args = [self.eval_expr(env, a) for a in e[3]]
            return self.call_method(env, tv, e[2], args)
        if k == "lambda":
            g = e[1]
            g.name = g.name or "<lambda>"
            # P6-wave fix: per-instance closure (see the gene-stmt arm).
            inst = copy.copy(g)
            inst.name = g.name
            inst.closure = env
            return inst
        if k == "collect":
            _, var, it, filt, body = e
            itv = self.eval_expr(env, it)
            if isinstance(itv, SeqObj):
                items = []
                while True:
                    v = itv.pull()
                    if v is None:
                        break
                    items.append(v)
            else:
                # #214: collect over a map iterates BOTH stores' keys;
                # z-s2-harden (#126.6): bytes collect as their int values
                # 0..=255 (W029 mirror, the for-statement convention) — the
                # comprehension used to yield [] for bytes
                items = itv if isinstance(itv, list) else (list(itv) if isinstance(itv, str) else (list(itv) if isinstance(itv, bytes) else (_map_keys(itv) if isinstance(itv, dict) else [])))
            out = []
            for item in items:
                self.tick()
                child = self.new_scope(env)
                child[var] = item
                if filt is not None and not truthy(self.eval_expr(child, filt)):
                    continue
                out.append(self.eval_expr(child, body))
            return out
        raise Stress("unfolded", f"unknown expression {k}")

    def as_index(self, v, ln):
        if isinstance(v, int) and not isinstance(v, bool):
            i = v
            if i < 0:
                i = ln + i
                if i < 0:
                    raise Stress("missing", f"index {v} out of range")
            return i
        raise Stress("missing", f"index must be int, found {type_name(v)}")

    def _f64_powf(self, a, b):
        # S4-5/F1b+F1c: Rust f64::powf mirror for the three spots where
        # python deviates from C99 pow: (1) a zero base (incl. -0.0) with a
        # negative exponent raises ZeroDivisionError — C99 gives ±inf, the
        # sign by parity of the exponent for a -0.0 base; (2) a negative
        # FINITE base with a non-integer exponent returns a python COMPLEX
        # (leaked into the renderer as <?>) — C99 gives NaN; (3) overflow
        # raises OverflowError — C99 gives ±inf (sign by parity for a
        # negative base). inf/nan bases and exponents already follow C99 in
        # python natively, so they fall through untouched.
        import math as _m
        if a == 0.0 and b < 0.0:
            if _m.copysign(1.0, a) < 0.0 and float(b).is_integer() and int(b) % 2 == 1:
                return float("-inf")
            return float("inf")
        if _m.isfinite(a) and a < 0.0 and _m.isfinite(b) and not float(b).is_integer():
            return float("nan")
        try:
            return a ** b
        except OverflowError:
            if a < 0.0 and float(b).is_integer() and int(b) % 2 == 1:
                return float("-inf")
            return float("inf")
