"""operon oracle: interp.method (split of bootstrap/oracle.py)."""

from ..annot import type_name
from ..fmt import truthy, v_display, v_repr
from ..mapops import _MAP_MISS, _map_del, _map_has, _map_items, _map_keys, _map_len, _map_lookup, _map_values, deep_eq
from ..values import Gene, ObjInst, SeqObj



class IMethod:

    # Deterministic walk budget (rt_p22a armor), the mirror of Rust
    # WALK_BUDGET: native graph walks are not fuel-accounted, so every
    # cycle walk carries a hard visit cap. Both cores visit in the same
    # order and cut at the same node; the cap never binds on sane graphs.
    WALK_BUDGET = 100_000

    def call_method(self, env, recv, name, args):
        if isinstance(recv, SeqObj):
            if name == "next":
                return recv.pull()
            if name == "collect":
                out = []
                while True:
                    v = recv.pull()
                    if v is None:
                        break
                    out.append(v)
                return out
            self.note(4, f"unknown sequence method '{name}'; null")
            return None
        if isinstance(recv, ObjInst):
            chain = []
            d = recv.defn
            hops = 0
            while d is not None and hops <= 32:
                chain.append(d)
                d = self.phenos.get(d.parent) if d.parent else None
                hops += 1
            for dd in chain:
                for g in dd.methods:
                    if g.name == name:
                        return self.call_method_gene(g, recv, args)
            # W04: trait default methods, implemented traits in declaration
            # order; virtual (self.x() inside dispatches through the lineage
            # first) because the fallback resolution is the same walk.
            for tname in recv.defn.implements:
                t = self.traits.get(tname)
                if t is None:
                    continue
                for m in t.methods:
                    if m.name == name and m.default is not None:
                        return self.call_method_gene(m.default, recv, args)
            if name in recv.fields:
                return self.call_value(env, recv.fields[name], args)
            self.note(4, f"phenotype {recv.defn.name} has no method '{name}'; null")
            return None
        if isinstance(recv, dict) and "#fate" in recv:
            fate_name, cur = recv["#fate"], recv["#state"]
            if name == "shift":
                target = v_display(args[0]) if args else ""
                states, _ = self.fates.get(fate_name, ([], None))
                allowed = any(f == cur and target in tg for f, tg in states)
                if allowed:
                    recv["#state"] = target
                    return True
                self.note(4, f"fate {fate_name}: '{cur}' → '{target}' crosses a valley; state held")
                return False
            if name == "state":
                return recv.get("#state")
            if name == "can":
                target = v_display(args[0]) if args else ""
                states, _ = self.fates.get(fate_name, ([], None))
                return any(f == cur and target in tg for f, tg in states)
        # W029 mirror: the bytes method surface, slice (Python-style,
        # clamped) and len. Bytes are immutable: no mutators by design.
        if isinstance(recv, bytes):
            if name == "slice":
                a = int(args[0]) if len(args) > 0 else 0
                b = int(args[1]) if len(args) > 1 else len(recv)
                return recv[a:b]
            if name == "len": return len(recv)
            self.note(4, f"unknown bytes method '{name}'; null")
            return None
        if isinstance(recv, str):
            if name == "at":
                # L1a: safe char access with an optional default
                i = args[0] if args else None
                if isinstance(i, bool) or not isinstance(i, int):
                    self.note(4, "at needs an int index; null")
                    return None
                j = len(recv) + i if i < 0 else i
                if 0 <= j < len(recv):
                    return recv[j]
                if len(args) > 1:
                    return args[1]
                self.note(4, "char index out of range; null")
                return None
            if name == "upper": return recv.upper()
            if name == "lower": return recv.lower()
            if name == "trim": return recv.strip()
            if name == "split":
                sep = v_display(args[0]) if args else " "
                return recv.split(sep)
            if name == "join":
                sep = recv
                lst = args[0] if args else []
                return sep.join(v_display(x) for x in lst)
            if name == "replace":
                return recv.replace(v_display(args[0]), v_display(args[1]))
            if name == "contains": return v_display(args[0]) in recv
            if name == "starts": return recv.startswith(v_display(args[0]))
            if name == "ends": return recv.endswith(v_display(args[0]))
            if name == "repeat": return recv * int(args[0])
            if name == "slice":
                a = int(args[0]) if len(args) > 0 else 0
                b = int(args[1]) if len(args) > 1 else len(recv)
                return recv[a:b]
            if name == "len": return len(recv)
        elif isinstance(recv, list):
            if name == "map":
                return [self.call_value(env, args[0], [x]) for x in recv]
            if name == "filter":
                return [x for x in recv if truthy(self.call_value(env, args[0], [x]))]
            if name == "reduce":
                acc = args[1] if len(args) > 1 else 0
                for x in recv:
                    acc = self.call_value(env, args[0], [acc, x])
                return acc
            if name == "each":
                for x in recv:
                    self.call_value(env, args[0], [x])
                return None
            if name == "sort":
                if args and isinstance(args[0], Gene):
                    # #137 (Z-137-SORTSTABLE): the comparator sort is STABLE
                    # (equal keys keep input order). This is the same walk the
                    # engine runs (comparator_sort, args in (cur, prev) order,
                    # one call per comparison) on a COPY — the immutable-method
                    # contract: recv is not mutated, a new list is returned.
                    out = list(recv)
                    cmp = args[0]
                    for i in range(1, len(out)):
                        j = i
                        while j > 0:
                            before = truthy(self.call_value(env, cmp, [out[j], out[j - 1]]))
                            if before:
                                out[j - 1], out[j] = out[j], out[j - 1]
                                j -= 1
                            else:
                                break
                    return out
                return sorted(recv, key=lambda x: (
                    (0, float(x), "") if isinstance(x, (int, float)) and not isinstance(x, bool)
                    else ((0, float(int(x)), "") if isinstance(x, bool)
                          else ((1, 0.0, x) if isinstance(x, str)
                                else (2, 0.0, v_repr(x))))
                ))
            if name == "reverse": return list(reversed(recv))
            if name == "contains": return any(deep_eq(x, args[0]) for x in recv)
            if name == "index_of":
                for i, x in enumerate(recv):
                    if deep_eq(x, args[0]):
                        return i
                return -1
            if name == "slice":
                a = int(args[0]) if len(args) > 0 else 0
                b = int(args[1]) if len(args) > 1 else len(recv)
                return recv[a:b]
            if name == "join":
                sep = v_display(args[0]) if args else ""
                return sep.join(v_display(x) for x in recv)
            if name == "len": return len(recv)
            if name == "push":
                if self.is_frozen(recv):
                    raise self._frozen_stress("list")
                self._cycle_note_insert(recv, args[0])  # W013: before the edge lands
                recv.append(args[0]); return recv
            if name == "pop":
                if self.is_frozen(recv):
                    raise self._frozen_stress("list")
                return recv.pop() if recv else None
            if name == "get":
                # L1a: safe index read with an optional default
                i = args[0] if args else None
                if isinstance(i, bool) or not isinstance(i, int):
                    self.note(4, "list get needs an int index; null")
                    return None
                j = len(recv) + i if i < 0 else i
                if 0 <= j < len(recv):
                    return recv[j]
                if len(args) > 1:
                    return args[1]
                self.note(4, "index out of range; null")
                return None
        elif isinstance(recv, dict):
            if name == "keys": return _map_keys(recv)
            if name == "values": return _map_values(recv)
            if name == "items": return [[k, v] for k, v in _map_items(recv)]
            if name == "get":
                # L1a: safe key access with an optional default
                # #214: _map_lookup already covers BOTH stores with the
                # deep_eq law — the old duplicate scan is retired
                key_q = args[0] if args else None
                t = _map_lookup(recv, key_q)
                if t is not _MAP_MISS:
                    return t
                if len(args) > 1:
                    return args[1]
                self.note(4, f"key '{v_display(key_q)}' missing; null")
                return None
            if name == "has": return _map_has(recv, args[0])
            if name == "del":
                if self.is_frozen(recv):
                    raise self._frozen_stress("map")
                _map_del(recv, args[0])
                return None
            if name == "len": return _map_len(recv)
            if name in recv and isinstance(recv[name], (Gene,)):
                return self.call_value(env, recv[name], args)
        self.note(4, f"{type_name(recv)} has no method '{name}'; null")
        return None
