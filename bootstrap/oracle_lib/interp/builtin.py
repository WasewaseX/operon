"""operon oracle: interp.builtin (split of bootstrap/oracle.py)."""

import unicodedata
import sys
import os
import math
import json as _json
from ..annot import type_name
from ..fmt import fmt_float, io_err, truthy, v_display, v_repr
from ..interp.builtin_tables import BUILTINS, BUILTIN_SYNONYMS
from ..lexer import edit_distance
from ..mapops import _MAP_MISS, _map_del, _map_has, _map_items, _map_keys, _map_len, _map_lookup, _map_member_get, _map_values, deep_eq
from ..values import Channel, Gene, M64, ObjInst, SeqObj, Stress, Variant, WeakRef, channel_degrade_result, channel_wire, grapheme_count, repressilator_levels



class IBuiltin:

    # ---- builtins
    def builtin(self, env, name, args):
        if name == "promote":
            print(" ".join(v_display(a) for a in args))
            return None
        if name == "len":
            v = args[0] if args else None
            if isinstance(v, (str, bytes, list)):
                return len(v)
            if isinstance(v, dict):
                return _map_len(v)
            self.note(4, "len() of non-container is 0")
            return 0
        # ---- W029: bytes conversions (UTF-8-only, explicit encoding)
        if name == "bytes_from_str":
            s = args[0] if args and isinstance(args[0], str) else None
            if s is None:
                raise Stress("unfolded", f"bytes_from_str needs a str, got {type_name(args[0] if args else None)}")
            if len(args) > 1:
                enc = v_display(args[1]).lower().replace("-", "")
                if enc != "utf8":
                    raise Stress("unfolded", f"unsupported encoding '{v_display(args[1])}' (bytes are UTF-8 only)")
            return s.encode("utf-8")
        if name == "str_from_bytes":
            b = args[0] if args and isinstance(args[0], bytes) else None
            if b is None and args and not isinstance(args[0], bytes):
                raise Stress("unfolded", f"str_from_bytes needs bytes, got {type_name(args[0])}")
            if len(args) > 1:
                enc = v_display(args[1]).lower().replace("-", "")
                if enc != "utf8":
                    raise Stress("unfolded", f"unsupported encoding '{v_display(args[1])}' (bytes are UTF-8 only)")
            if b is None:
                return ""
            try:
                return b.decode("utf-8")
            except UnicodeDecodeError as e:
                # soft tier: null + note naming the offending byte position
                self.note(4, f"str_from_bytes: invalid UTF-8 at byte {e.start}; null")
                return None
        if name == "bytes_from_list":
            if not args or args[0] is None:
                return b""
            l = args[0]
            if not isinstance(l, list):
                raise Stress("unfolded", f"bytes_from_list needs a list, got {type_name(l)}")
            out = bytearray()
            for v in l:
                if isinstance(v, bool) or not isinstance(v, int):
                    raise Stress("unfolded", f"bytes_from_list needs ints, got {type_name(v)}")
                if not (0 <= v <= 255):
                    raise Stress("unfolded", f"byte value {v} out of range 0..255")
                out.append(v)
            return bytes(out)
        if name == "bytes_to_list":
            b = args[0] if args else None
            if b is None:
                return []
            if not isinstance(b, bytes):
                raise Stress("unfolded", f"bytes_to_list needs bytes, got {type_name(b)}")
            return list(b)
        if name == "push":
            if self.is_frozen(args[0]):
                raise self._frozen_stress("list")
            self._cycle_note_insert(args[0], args[1])  # W013: before the edge lands
            args[0].append(args[1]); return args[0]
        if name == "pop":
            if self.is_frozen(args[0]):
                raise self._frozen_stress("list")
            return args[0].pop() if args[0] else None
        if name == "insert":
            if self.is_frozen(args[0]):
                raise self._frozen_stress("list")
            idx = self.as_index(args[1], len(args[0]))
            self._cycle_note_insert(args[0], args[2])  # W013: before the edge lands
            args[0].insert(min(idx, len(args[0])), args[2]); return args[0]
        if name == "remove":
            if self.is_frozen(args[0]):
                raise self._frozen_stress("list")
            idx = self.as_index(args[1], len(args[0]))
            if idx < len(args[0]):
                return args[0].pop(idx)
            raise Stress("missing", "remove index out of range")
        if name == "keys":
            return _map_keys(args[0]) if isinstance(args[0], dict) else []
        if name == "values":
            return _map_values(args[0]) if isinstance(args[0], dict) else []
        if name == "has":
            return isinstance(args[0], dict) and _map_has(args[0], args[1])
        if name == "del":
            # F-DELNOTE (note-parity): mirror of the Rust call_builtin "del"
            # fallback arm — a 1-arg / 0-arg / non-map del() used to return
            # null silently on BOTH engines while range() notes by
            # convention. (args is the RAW list here — no padding — so the
            # len check distinguishes an ABSENT second arg from an explicit
            # del(m, null), exactly like Rust's args.get(1) Option.)
            if len(args) >= 2 and isinstance(args[0], dict):
                if self.is_frozen(args[0]):
                    raise self._frozen_stress("map")
                _map_del(args[0], args[1])
                return None
            # A13/dx-r2 location law: notes carry real locations — pass the
            # executing call's line so the flush renders `[tag] file:line: msg`
            # byte-identically to tools::flush_notes (line=0 renders UNLOCATED,
            # a latent asymmetry this arm would otherwise bake in).
            self.note(4, "del() needs a map and a key; ignored", self.cur_line)
            return None
        if name == "range":
            # P2P3P5 pin found the latent gap: the Rust engine notes and
            # returns [] on any non-int arg; the oracle walked into Python
            # TypeError instead (int < str). Mirror the note + [] exactly.
            if not all(
                isinstance(x, int) and not isinstance(x, bool) for x in args
            ):
                # F-DELNOTE sibling found during the fix: the range note had
                # the same latent line=0 rendering gap (unlocated stderr vs
                # the engine's located render). Same one-line law.
                self.note(4, "range() needs ints; returned []", self.cur_line)
                return []
            if len(args) == 1:
                a, b, st = 0, args[0], 1
            elif len(args) == 2:
                a, b, st = args[0], args[1], 1
            else:
                a, b, st = args[0], args[1], args[2]
            if st == 0:
                raise Stress("unfolded", "range step cannot be 0")
            out = []
            i = a
            while (st > 0 and i < b) or (st < 0 and i > b):
                out.append(i)
                i += st
                if len(out) > 10_000_000:
                    raise Stress("overflow", "range too large")
            return out
        if name == "str":
            return v_display(args[0]) if args else ""
        if name == "num":
            v = args[0] if args else None
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return v
            try:
                t = str(v).strip()
                return int(t)
            except ValueError:
                try:
                    return float(t)
                except (ValueError, UnboundLocalError):
                    self.note(4, f"num('{v}') failed; 0")
                    return 0
        if name == "type":
            if args and isinstance(args[0], ObjInst):
                return args[0].defn.name
            return type_name(args[0]) if args else "null"
        if name == "abs":
            a0 = args[0] if args else 0
            if isinstance(a0, int) and not isinstance(a0, bool) and a0 == -(2**63):
                raise Stress("overflow", "int overflow in abs(i64::MIN)")
            return abs(a0)
        if name in ("min", "max"):
            vals = []
            for a in args:
                if isinstance(a, list):
                    vals.extend(a)
                else:
                    vals.append(a)
            if not vals:
                return None
            return (min if name == "min" else max)(vals)
        if name == "sum":
            src = args[0] if len(args) == 1 and isinstance(args[0], list) else args
            acc = 0
            for v in src:
                acc = self.binop("+", acc, v)
            return acc
        if name == "clock":
            import time
            return time.monotonic()
        if name == "now":
            import time
            return time.monotonic()
        if name == "exit":
            # sec-r2 (audit C-11) mirror: process exit is a capability,
            # default-deny. S3 found the old unconditional sys.exit()
            # diverging from the rust refusal surface (rust: catchable
            # interference + the runner survives; oracle: process died).
            # allow-all (enabled False) implies exit, as Caps::allow_all does.
            c = self.caps
            if c["enabled"] and not c.get("exit"):
                self.note(4, "exit denied: capability 'exit' not granted (grant with --allow-exit or .cell allow.exit = true)")
                raise Stress("interference", "exit denied, capability 'exit' not granted (grant with --allow-exit or .cell allow.exit = true)")
            sys.exit(int(args[0]) if args else 0)
        if name == "assert":
            ok = truthy(args[0]) if args else False
            # S4-6b: count every EXECUTED assert (pass or burn), mirroring
            # interp.rs's asserts_run += 1 before the burn check — the
            # proof-integrity vacuous-proof rule reads this counter.
            self.asserts_run += 1
            if not ok:
                msg = v_display(args[1]) if len(args) > 1 else "assertion failed"
                raise Stress("burned", msg)
            return True
        if name == "codon":
            s = v_display(args[0]) if args else ""
            # mirror of the C++ kernel: 3-letter groups scored by usage class
            USAGE = [7,1,5,3,15,6,8,4,3,2,0,0,4,6,0,5,
                     4,1,2,13,5,2,4,1,6,2,12,9,5,3,9,4,
                     3,1,2,15,8,5,6,2,14,7,12,6,2,1,8,3,
                     6,2,8,1,8,3,6,10,4,2,13,11,6,7,3,9]
            def bidx(c):
                return {"t": 0, "u": 0, "c": 1, "a": 2, "g": 3}.get(c.lower(), -1)
            acc, groups = 0, 0
            s2 = v_display(args[0]) if args else ""
            i = 0
            while i + 2 < len(s2):
                b1, b2, b3 = bidx(s2[i]), bidx(s2[i+1]), bidx(s2[i+2])
                if b1 < 0 or b2 < 0 or b3 < 0:
                    # reg-r4 (re-audit B-2): NEUTRAL 50, mirroring the kernel
                    # (never reward biological nonsense, never punish ids)
                    acc += 50
                else:
                    w = USAGE[b1 * 16 + b2 * 4 + b3]
                    acc += 30 + w * 5
                groups += 1
                i += 3
            if groups == 0:
                return 0
            mean = acc // groups
            return int(min(mean, 100))
        if name == "distance":
            a = v_display(args[0]) if args else ""
            b = v_display(args[1]) if len(args) > 1 else ""
            return edit_distance(a, b)
        if name == "similar":
            a = v_display(args[0]) if args else ""
            b = v_display(args[1]) if len(args) > 1 else ""
            maxd = int(args[2]) if len(args) > 2 else 2
            return edit_distance(a, b) <= maxd
        if name == "transcribe":
            s = (v_display(args[0]) if args else "").upper()
            return s.replace("T", "U")
        if name == "reverse_complement":
            s = (v_display(args[0]) if args else "").upper()
            comp = {"A": "T", "T": "A", "G": "C", "C": "G"}
            return "".join(comp.get(c, c) for c in reversed(s))
        if name == "gc_content":
            s = (v_display(args[0]) if args else "").upper()
            n = sum(1 for c in s if c in "ATGC")
            if n == 0:
                return 0.0
            gc = sum(1 for c in s if c in "GC")
            return gc * 100.0 / n
        if name == "translate":
            s = (v_display(args[0]) if args else "").upper()
            TABLE = {}
            bases = "TCAG"
            aas = "FFLLSSSSYY**CC*WLLLLPPPPHHQQRRRRIIIMTTTTNNKKSSRRVVVVAAAADDEEGGGG"
            i = 0
            for b1 in bases:
                for b2 in bases:
                    for b3 in bases:
                        TABLE[b1 + b2 + b3] = aas[i]
                        i += 1
            # NOTE: this enumeration order is TTT,TTC,TTA,TTG,TCT... (b3 fastest)
            protein = []
            s2 = s.replace("U", "T")
            i = 0
            while i + 3 <= len(s2):
                codon = s2[i:i + 3]
                if codon in ("TAA", "TAG", "TGA"):
                    break
                aa = None
                for kk, vv in (("TTT","F"),("TTC","F"),("TTA","L"),("TTG","L"),
                               ("TCT","S"),("TCC","S"),("TCA","S"),("TCG","S"),
                               ("TAT","Y"),("TAC","Y"),("TAA","*"),("TAG","*"),
                               ("TGT","C"),("TGC","C"),("TGA","*"),("TGG","W"),
                               ("CTT","L"),("CTC","L"),("CTA","L"),("CTG","L"),
                               ("CCT","P"),("CCC","P"),("CCA","P"),("CCG","P"),
                               ("CAT","H"),("CAC","H"),("CAA","Q"),("CAG","Q"),
                               ("CGT","R"),("CGC","R"),("CGA","R"),("CGG","R"),
                               ("ATT","I"),("ATC","I"),("ATA","I"),("ATG","M"),
                               ("ACT","T"),("ACC","T"),("ACA","T"),("ACG","T"),
                               ("AAT","N"),("AAC","N"),("AAA","K"),("AAG","K"),
                               ("AGT","S"),("AGC","S"),("AGA","R"),("AGG","R"),
                               ("GTT","V"),("GTC","V"),("GTA","V"),("GTG","V"),
                               ("GCT","A"),("GCC","A"),("GCA","A"),("GCG","A"),
                               ("GAT","D"),("GAC","D"),("GAA","E"),("GAG","E"),
                               ("GGT","G"),("GGC","G"),("GGA","G"),("GGG","G")):
                    if kk == codon:
                        aa = vv
                        break
                protein.append(aa or "X")
                i += 3
            return "".join(protein)
        if name == "find_orf":
            s = (v_display(args[0]) if args else "").upper()
            out = []
            i = 0
            while i + 2 < len(s):
                if s[i:i+3] == "ATG":
                    j = i
                    protein = []
                    stopped = False
                    while j + 2 < len(s):
                        c2 = s[j:j+3]
                        if c2 in ("TAA", "TAG", "TGA"):
                            stopped = True
                            break
                        protein.append(self.builtin(env, "translate", [c2]) or "")
                        j += 3
                    if stopped and protein:
                        out.append("".join(protein))
                i += 1
            return out
        if name == "memory":
            # W59 windows truth (2026-09-29): a dead `import resource` sat
            # here - unix-only module, zero usages - and every memory()
            # call died with ModuleNotFoundError on Windows (first divergence
            # in tests/differential/weak_refs.op, the CI-native windows job).
            # The import is gone; the dict below never referenced it.
            # W013 (D-013): the cycles field mirrors the Rust live detected-
            # cycle gauge (insertion registers, reclamation prunes); the
            # other three keys are Rust symbol-table gauges the sequential
            # oracle does not have (zeros, the pre-existing shape contract).
            return {"arena_bytes": 0, "interns": 0, "allocs": 0,
                    "cycles": self._live_cycles()}
        if name == "weak":
            # W013: supported targets are the container values (list, map,
            # phenotype instance); everything else is refused (SPEC §19f).
            # No-argument call mirrors the Rust None-arm message exactly.
            if not args:
                raise Stress("unfolded", "weak(v) needs a list, map, or phenotype")
            v = args[0]
            if isinstance(v, list):
                self.weak_targets[id(v)] = ("list", v, None)
                return WeakRef("list", id(v))
            if isinstance(v, dict):
                self.weak_targets[id(v)] = ("map", v, None)
                return WeakRef("map", id(v))
            if isinstance(v, ObjInst):
                self.weak_targets[id(v.fields)] = ("phenotype", v.fields, v.defn)
                return WeakRef("phenotype", id(v.fields), v.defn)
            raise Stress("unfolded",
                         f"weak() needs a list, map, or phenotype, found {type_name(v)}")
        if name == "strengthen":
            if not args:
                # no-argument call mirrors the Rust None-arm message exactly
                raise Stress("unfolded", "strengthen(w) needs a weak handle")
            w = args[0]
            if not isinstance(w, WeakRef):
                raise Stress("unfolded",
                             f"strengthen(w) needs a weak handle, found {type_name(w)}")
            entry = self.weak_targets.get(w.addr)
            if entry is None or not self._weak_binding_alive(env, w.addr):
                # no GC: the last strong ref freed the target immediately;
                # the soft note is Rust-lane, the oracle just returns null
                return None
            t = entry[1]
            if w.kind == "phenotype":
                return ObjInst(w.defn, t)
            return t
        if name == "methyl":
            k = v_display(args[0]) if args else ""
            d = args[1] if len(args) > 1 else None
            v = self.cell.get(k)
            if v is None:
                return d
            if v == "true": return True
            if v == "false": return False
            try:
                return int(v)
            except ValueError:
                try:
                    return float(v)
                except ValueError:
                    return v
        if name == "splice_shift":
            # loop-9 (F-4): mirror of the Rust builtin, rebinds the splice
            # root to the named variant exactly like the splice statement.
            root = v_display(args[0]) if args else ""
            variant = v_display(args[1]) if len(args) > 1 else ""
            sp = self.splice_registry.get(root)
            if sp is None:
                self.note(4, f"splice_shift: no splice '{root}'; selection unchanged")
                return None
            variants = sp[2]
            if not any(v[0] == variant for v in variants):
                cur = self.choose_variant(root, variants)
                cur = cur[0] if cur else ""
                self.note(4, f"splice_shift: variant '{variant}' not declared in splice '{root}'; selection unchanged")
                return cur
            self.splice_shift[root] = variant
            vname, vparams, body, vmarks, vline = self.choose_variant(root, variants)
            g = Gene(root, vparams, None, body,
                     ac="acetylate" in vmarks, me="methylate" in vmarks, m6="m6a" in vmarks, line=vline)
            if root not in self.defined_genes:
                self.defined_genes.append(root)
            # trans-acting factor: replace the binding up the env chain
            self.assign(env, root, g)
            self.note(1, f"splice shift: '{root}' -> variant '{variant}' (was '{vname}')")
            return vname
        if name in ("m6a_write", "m6a_erase"):
            # reg-bio-3 (B3): quantitative m6A site density 0..=3 (mirror)
            k = v_display(args[0]) if args else ""
            n = args[1] if len(args) > 1 and isinstance(args[1], int) and not isinstance(args[1], bool) else 1
            n = max(n, 0)
            if name == "m6a_write":
                lvl = min(self.m6a_levels.get(k, 0) + n, 3)
                verb = "written"
            else:
                lvl = max(0, self.m6a_levels.get(k, 0) - n)
                verb = "erased"
            self.m6a_levels[k] = lvl
            marked = lvl >= 1
            if not self.methyl_quiet:
                self.note(2, f"m6A {verb}: '{k}' (level {lvl}), redefinition {'resisted' if marked else 'no longer resisted'}")
            return lvl
        if name == "passage":
            # reg-bio-3 (B2/B6): cell divisions, marks dilute unless
            # maintained (mirror of the Rust passage builtin)
            n = args[0] if args and isinstance(args[0], int) and not isinstance(args[0], bool) else 1
            n = max(n, 0)
            if n > 1_000_000:
                self.note(4, "passage: n clamped to 1000000 divisions (a culture that old is not a useful model)")
                n = 1_000_000
            f = self.cell.get("methyl.maintenance")
            fv = 0.5
            if f is not None:
                try:
                    fv = min(max(float(f), 0.0), 1.0)
                except ValueError:
                    fv = 0.5
            import math as _math
            for _i in range(n):
                for k2 in list(self.methyl_levels):
                    x = self.methyl_levels[k2] * fv - 0.5
                    self.methyl_levels[k2] = max(0, int(_math.ceil(x)))
            # loop-9 (C8): the signal medium dilutes with the culture,
            # floor(m * d) per division, d = .cell quorum.dilution (default
            # 0.5, binary-exact halving). Empty medium = no-op (mirror).
            qd = self.cell.get("quorum.dilution")
            qdv = 0.5
            if qd is not None:
                try:
                    qdv = min(max(float(qd), 0.0), 1.0)
                except ValueError:
                    qdv = 0.5
            for _i in range(n):
                for k2 in list(self.medium):
                    self.medium[k2] = int(_math.floor(self.medium[k2] * qdv))
            self.generation += n
            if not self.methyl_quiet:
                self.note(1, f"passage: {n} divisions (maintenance {fv!r}), generation {self.generation}")
            return self.generation
        if name == "methylate":
            # A12 (reg-r2): mirror of the Rust runtime API, same graded
            # semantics as the @methylate attribute (D-005): level += 1.
            k = v_display(args[0]) if args else ""
            self.methyl_levels[k] = self.methyl_levels.get(k, 0) + 1
            return self.methyl_levels[k]
        if name == "demethylate":
            # A12: the @acetylate direction, saturating relaxation.
            k = v_display(args[0]) if args else ""
            self.methyl_levels[k] = max(0, self.methyl_levels.get(k, 0) - 1)
            return self.methyl_levels[k]
        if name == "grn_set":
            # A12: write a GRN node's level directly (0..1, clamped).
            k = v_display(args[0]) if args else ""
            v = args[1] if len(args) > 1 else 0.0
            if not isinstance(v, float):
                v = float(v)
            v = min(max(v, 0.0), 1.0)
            self.grn_levels[k] = v
            return v
        if name == "grn_get":
            # A12: read a GRN node's level.
            k = v_display(args[0]) if args else ""
            return self.grn_levels.get(k, 0.0)
        if name == "fingerprint":
            # loop-9 (P0-3): parity fix, the Rust core measures COMPLETE
            # 20-call bins only (`call_clock / 20`); this mirror's former
            # `+ 1` included the trailing partial bin, so the same 41-call
            # history scored 2.439 on Rust and 0.053 here. Mirror the
            # complete-bin rule op-for-op (complete_bins == 0 lists the gene
            # at 0.0 but excludes it from the average, exactly like Rust).
            complete_bins = self.call_clock // 20
            burst_by = {}
            burst_total, burst_n = 0.0, 0
            # reg-bio-2 (D9): iterate buckets in SORTED key order, the Rust
            # core accumulates burst_total in sorted order (float addition is
            # not associative; order must match for the last-ulp parity).
            for gname in sorted(self.gene_buckets):
                bins = self.gene_buckets[gname]
                if complete_bins == 0:
                    burst_by[gname] = 0.0
                    continue
                n = float(complete_bins)
                total = sum(bins.get(b, 0) for b in range(complete_bins))
                mean = total / n
                # reg-bio-2 (D9): d*d (explicit multiply), never **, op-for-op
                # with the Rust core's un-multiplied square.
                var = 0.0
                for b in range(complete_bins):
                    d = float(bins.get(b, 0)) - mean
                    var += d * d
                var /= n
                burst = (var / mean) if mean > 0 else 0.0
                burst_by[gname] = burst
                burst_total += burst
                burst_n += 1
            burst_avg = (burst_total / burst_n) if burst_n else 0.0
            total_defined = len(self.defined_genes)
            mature = min(len(self.call_counts), total_defined)
            nascent = max(total_defined - mature, 0)
            maturation = (mature / total_defined) if total_defined else 0.0
            # reg-bio-2 (D9): "calls" emits in sorted key order (Rust parity).
            # reg-bio-3 (A1/A7/B2): polycistronic transcript counts + division
            # counter (sorted-key determinism, D9) (mirror)
            transcripts = {u["name"]: u["transcripts"] for u in self.operons}
            return {"calls": dict(sorted(self.call_counts.items())), "burst": burst_avg,
                    "burst_by_gene": dict(sorted(burst_by.items())),
                    "bursts": dict(sorted(self.burst_off.items())),
                    "mature": mature, "nascent": nascent, "maturation": maturation,
                    "transcripts": dict(sorted(transcripts.items())),
                    "generation": self.generation}
        if name == "toggle_on":
            nm = v_display(args[0]) if args else ""
            for i, (a, b, _on) in enumerate(self.toggles):
                if nm in (a, b):
                    self.toggles[i] = (a, b, a == nm)
                    return True
            self.note(4, f"toggle pair containing '{nm}' not declared")
            return False
        if name == "toggle_state":
            out = {}
            for a, b, a_on in self.toggles:
                out[a] = a_on
                out[b] = not a_on
            return out
        if name == "repressi_next":
            if not self.repressi_ring:
                self.note(4, "no repressilator declared")
                return None
            self.repressi_i = (self.repressi_i + 1) % len(self.repressi_ring)
            self.repressi_tick += 1
            return self.repressi_i
        if name == "repressi_start":
            if not self.repressi_ring:
                self.note(4, "repressi_start: no repressilator ring declared")
                return False
            ms = 1000
            if args and isinstance(args[0], (int, float)):
                ms = int(max(args[0], 0))
            if ms == 0:
                self.note(4, "repressi_start period must be > 0 ms")
                return False
            self.note(1, f"repressilator oscillating every {ms} ms (sequential oracle: manual ring only)")
            return True
        if name == "repressi_state":
            # A11 (reg-r2), mirror of the Rust core: the ring integrates
            # the discrete Elowitz–Leibler repressilator. State is a pure
            # function of the tick count; arithmetic order matches Rust
            # op-for-op (bit-identical IEEE-754).
            n = len(self.repressi_ring)
            if not n:
                return {}
            lvls = repressilator_levels(n, self.repressi_tick, self.repressi_params)
            return {nm: lvls[j] for j, nm in enumerate(self.repressi_ring)}
        if name == "grn_fire":
            seed = v_display(args[0]) if args else ""
            # A10 (reg-r2): decay mirror, decay comes from the pulse itself
            # (grn_fire(seed, f)) or falls back to .cell `[grn] decay`;
            # unset/0 skips the loop (byte-identical to pre-A10).
            raw_decay = args[1] if len(args) > 1 else None
            if raw_decay is not None:
                if not isinstance(raw_decay, float):
                    raw_decay = float(raw_decay)
                decay = min(max(raw_decay, 0.0), 1.0)
            else:
                decay = self.cell.get("grn.decay")
                try:
                    decay = min(max(float(decay), 0.0), 1.0) if decay is not None else 0.0
                except ValueError:
                    decay = 0.0
            if decay > 0.0 and self.grn_levels:
                retention = 1.0 - decay
                for k2 in self.grn_levels:
                    self.grn_levels[k2] *= retention
                    if self.grn_levels[k2] < 2.220446049250313e-16:  # f64::EPSILON
                        self.grn_levels[k2] = 0.0
            # reg-bio-2 (C1): the translation layer integrates at every
            # engine update point (mirror of the Rust grn_fire).
            self._trans_integrate()
            # STATEFUL network: levels persist across fires (a latch by default, decay makes the dilution explicit)
            # loop-9 (P0-2): ligand/signal-backed endpoints stay OUT of
            # grn_levels (they resolve through their own pools, seeding
            # them at 0.0 would shadow those reads forever) (mirror).
            for frm, to, st, inh, thr, hill, is_any, occupy, is_sum, attenuating in self.grn_edges:
                if frm not in self.ligands and frm not in self.signals:
                    self.grn_levels.setdefault(frm, 0.0)
                if to not in self.ligands and to not in self.signals:
                    self.grn_levels.setdefault(to, 0.0)
            # loop-9 (C8): firing a signal species directly would shadow the
            # medium read, the Rust core refuses with a note (mirror).
            if seed in self.signals:
                self.note(4, f"'{seed}' is a signal species: its level lives in the shared medium, use secrete()")
            else:
                self.grn_levels[seed] = min(self.grn_levels.get(seed, 0.0) + 1.0, 1.0)
            # reg-r3 (re-audit): TWO-PHASE fire, mirroring the Rust core and
            # the SPEC exactly, phase 1 propagates ACTIVATION in waves with
            # inhibitors excluded; phase 2 applies each inhibitor ONCE,
            # post-activation. (The old mirror subtracted inside the wave
            # loop, up to 10 times, diverging from the SPEC's "applied
            # exactly once per fire"; a pre-charged inhibited target shows
            # it: Rust yields 0.1, the old mirror yielded 0.0.)
            for wave in range(1, 11):
                changed = False
                snap = dict(self.grn_levels)
                for frm, to, st, inh, thr, hill, is_any, occupy, is_sum, attenuating in self.grn_edges:
                    if inh:
                        continue  # inhibitors propagate in phase 2
                    if is_sum:
                        continue  # pooled edges propagate as groups, below
                    parent = snap.get(frm, 0.0)
                    if parent <= 0:
                        continue
                    # reg-bio-2 (C11): propagation reads the FREE fraction
                    parent = self._regulated_level(parent, frm)
                    if thr is not None and thr > 0.0:
                        # reg-bio (F-2): per-edge Hill exponent (mirror of
                        # the Rust repeated multiplication, never **)
                        n_h = hill if hill is not None else 2
                        ph = 1.0
                        th2 = 1.0
                        for _k in range(n_h):
                            ph *= parent
                            th2 *= thr
                        influence = st * (ph / (ph + th2))
                    else:
                        # op-identical to the Rust repeated multiplication
                        # (never **, pow vs mul rounding must not diverge)
                        s = st
                        for _ in range(wave - 1):
                            s *= st
                        influence = parent * s
                    cur = self.grn_levels.get(to, 0.0)
                    # reg-bio-2 (D2c): influence clamps at 1.0 (mirror)
                    nxt = max(cur, min(influence, 1.0))
                    if abs(nxt - cur) > 1e-12:
                        self.grn_levels[to] = nxt
                        changed = True
                # reg-bio-2 (B7): pooled (`sum`) edges, group pass per wave,
                # BEFORE the convergence check (mirror of the Rust core).
                groups = []
                for frm, to, st, inh, thr, hill, is_any, occupy, is_sum, attenuating in self.grn_edges:
                    if inh or not is_sum:
                        continue
                    if thr is None or thr <= 0.0:
                        continue
                    parent = snap.get(frm, 0.0)
                    parent = self._regulated_level(parent, frm)
                    n_h = hill if hill is not None else 2
                    for g in groups:
                        if g[0] == to and g[1] == thr and g[2] == n_h:
                            g[3] += st * parent
                            break
                    else:
                        groups.append([to, thr, n_h, st * parent])
                for to, thr, n_h, pooled in groups:
                    p = min(pooled, 1.0)
                    ph = 1.0
                    th2 = 1.0
                    for _k in range(n_h):
                        ph *= p
                        th2 *= thr
                    influence = ph / (ph + th2)
                    cur = self.grn_levels.get(to, 0.0)
                    nxt = max(cur, min(influence, 1.0))
                    if abs(nxt - cur) > 1e-12:
                        self.grn_levels[to] = nxt
                        changed = True
                if not changed:
                    break
            # phase 2: inhibition subtracts once, from the source's
            # post-activation level (sources read the PRE-phase-2 snapshot,
            # parity with the Rust `activated` map, so a node that is both a
            # target and a later source keeps its post-activation level)
            post = dict(self.grn_levels)
            for frm, to, st, inh, thr, hill, is_any, occupy, is_sum, attenuating in self.grn_edges:
                if not inh:
                    continue
                parent = post.get(frm, 0.0)
                if parent <= 0.0:
                    continue
                # reg-bio-2 (C11): inhibition also reads the FREE fraction
                parent = self._regulated_level(parent, frm)
                if thr is not None and thr > 0.0:
                    # reg-bio (F-2): cooperative repressor influence
                    n_h = hill if hill is not None else 2
                    ph = 1.0
                    th2 = 1.0
                    for _k in range(n_h):
                        ph *= parent
                        th2 *= thr
                    influence = st * (ph / (ph + th2))
                else:
                    influence = parent * st
                cur = self.grn_levels.get(to, 0.0)
                # reg-bio-2 (D2b): occupancy repression, multiplicative
                # survival (mirror of the Rust core); legacy subtracts once.
                if occupy:
                    self.grn_levels[to] = cur * (1.0 - min(influence, 1.0))
                else:
                    self.grn_levels[to] = max(0.0, cur - influence)
            return dict(sorted(self.grn_levels.items()))
        if name == "grn_state":
            # reg-bio-2 (D9): sorted key order, Rust HashMap order varies per
            # process; both implementations now emit byte-order sorted maps.
            return dict(sorted(self.grn_levels.items()))
        if name == "items":
            v = args[0] if args else {}
            if isinstance(v, dict):
                # Z-MAPORDER: the unified insertion sequence (head+tail)
                return [[k, val] for k, val in _map_items(v)]
            return []
        if name == "spawn":
            callee = args[0] if args else None
            targs = args[1] if len(args) > 1 and isinstance(args[1], list) else []
            if isinstance(callee, Gene):
                # W013 spawn membrane mirror: a top-level weak handle is
                # REFUSED with the same catchable `membrane` stress as the
                # Rust pre-flight (a weak handle's target identity cannot
                # cross a cell boundary; nested handles keep the degrade-
                # to-null wire rule)
                for _a in targs:
                    if isinstance(_a, WeakRef):
                        raise Stress(
                            "membrane",
                            "spawn() refuses a weak payload; weak handles cannot cross the snapshot membrane")
                # reg-r4: SendValue depth ceiling mirror (Rust SEND_DEPTH_CAP
                # = 100_000), deep spawn payloads raise a catchable
                # `overflow` stress exactly like the Rust serialization path
                for _a in targs:
                    _stack = [(_a, 1)]
                    while _stack:
                        _item, _d = _stack.pop()
                        if _d > 100_000:
                            raise Stress("overflow", "spawn payload exceeds the depth ceiling")
                        if isinstance(_item, list):
                            _stack.extend((x, _d + 1) for x in _item)
                        elif isinstance(_item, dict):
                            # Z-MAPORDER: the spawn-membrane depth pre-walk
                            # sees BOTH stores (same class as the send walk)
                            _stack.extend((x, _d + 1) for x in _map_values(_item))
                # reg-r4 (re-audit B-2): route through call_named like the
                # Rust worker does, a direct call_gene bypasses the
                # toggle/RISC/GRN/methyl gates ("a repressed allele stays
                # repressed in worker cells", reg-r1's own contract)
                # reg-bio-2 (C3): worker RNG decorrelation mirror, the Rust
                # worker derives its stream from the task id; the sequential
                # oracle runs the body inline but saves / derives / restores
                # the host stream, so stochastic worker bodies draw from the
                # identical derived sequence bit-for-bit.
                _saved_rng = self.rng
                _task_id = getattr(self, "next_id", 0) + 1
                _derived = (0x9E3779B97F4A7C15 ^ ((_task_id * 0x9E3779B97F4A7C15) & M64)) & M64
                self.rng = _derived
                spawn_name = callee.name
                # loop-9 (C8): the Rust worker tags its notes "[task <name>]"
                #, mirror the prefix while the body runs inline
                _saved_prefix = getattr(self, "task_note_prefix", None)
                self.task_note_prefix = f"[task {spawn_name or '<lambda>'}]"
                # loop-9: worker-cell isolation (mirror of the snapshot
                # semantics), the Rust worker gets a COPY of regulation
                # state and FRESH expression counters; mutations inside the
                # cell never propagate to the host. The sequential oracle
                # must save/restore everything the snapshot carries.
                _saved_state = {
                    "grn_edges": list(self.grn_edges),
                    "grn_levels": dict(self.grn_levels),
                    "toggles": list(self.toggles),
                    "methyl_levels": dict(self.methyl_levels),
                    "methyl_threshold": self.methyl_threshold,
                    "enhanced": list(self.enhanced),
                    "repressi_ring": list(self.repressi_ring),
                    "repressi_tick": self.repressi_tick,
                    "repressi_params": dict(self.repressi_params),
                    "promoter_states": dict(self.promoter_states),
                    "burst_off": dict(self.burst_off),
                    "expr_stochastic": self.expr_stochastic,
                    "expr_kon": self.expr_kon,
                    "expr_koff": self.expr_koff,
                    "decay_clock_n": self.decay_clock_n,
                    "decay_clock_f": self.decay_clock_f,
                    "trans_edges": list(self.trans_edges),
                    "trans_last": dict(self.trans_last),
                    "decoys": list(self.decoys),
                    "ligands": list(self.ligands),
                    "ligand_pools": dict(self.ligand_pools),
                    "grn_binds": list(self.grn_binds),
                    "silences": list(self.silences),
                    "risc_escaped": set(self.risc_escaped),
                    "operons": [dict(u) for u in self.operons],
                    "m6a_levels": dict(self.m6a_levels),
                    "generation": self.generation,
                    "copies": dict(self.copies),
                    "signals": list(self.signals),
                    "splice_shift": dict(self.splice_shift),
                    "promoter_tel": dict(self.promoter_tel),
                    "burst_overrides": dict(self.burst_overrides),
                    "rho_pins": self.rho_pins,
                    "ribo_queue": dict(self.ribo_queue),
                    "call_counts": dict(self.call_counts),
                    "call_clock": self.call_clock,
                    "gene_buckets": {k: dict(v) for k, v in self.gene_buckets.items()},
                    "defined_genes": list(self.defined_genes),
                    "methyl_noted": set(self.methyl_noted),
                }
                # the worker starts with FRESH expression counters (its own
                # call clock starts at zero)
                self.call_counts = {}
                self.call_clock = 0
                self.gene_buckets = {}
                # W05 spawn boundary: the Rust worker receives serialized
                # COPIES of the arguments (nothing reachable from them is
                # frozen inside the worker). Park the reachable frozen ids
                # for the inline body, restore after, byte-parity with the
                # per-interpreter registry semantics.
                _parked_frozen = self._park_frozen_reachable(targs)
                try:
                    try:
                        if spawn_name:
                            result = self.call_named(env, spawn_name, targs)
                        else:
                            result = self.call_value(env, callee, targs)
                    finally:
                        self._restore_frozen(_parked_frozen)
                except Stress as st:
                    # W06 (D-014) mirror: a propagated variant IS the worker
                    # gene's return value, converted at the boundary.
                    if st.prop is not None:
                        result = st.prop
                    else:
                        result = {"kind": st.kind, "message": st.message}
                finally:
                    for k2, v2 in _saved_state.items():
                        setattr(self, k2, v2)
                    self.rng = _saved_rng
                    self.task_note_prefix = _saved_prefix
                # W015 mirror: the result crosses the join membrane, a
                # channel handle degrades to null exactly like the Rust
                # to_send path (deeply inside containers and variant
                # payloads, both the return and the propagated paths)
                result = channel_degrade_result(result)
                self.next_id = _task_id
                self.tasks = getattr(self, "tasks", {})
                self.tasks[self.next_id] = result
                # W18: the sequential engine ran the body inline, so the
                # task is born finished; the phase tombstone mirrors the
                # Rust registry's post-join answer
                _tombs = getattr(self, "task_tombstones", {})
                _tombs[self.next_id] = "done"
                self.task_tombstones = _tombs
                # W17: register on the innermost scope block, mirroring the
                # Rust spawn's scope registration
                _scopes = getattr(self, "scope_stack", None)
                if _scopes:
                    _scopes[-1].append(self.next_id)
                return self.next_id
            self.note(4, "spawn() needs a gene; null task")
            return None
        if name == "join":
            tid = args[0] if args else None
            tasks = getattr(self, "tasks", {})
            if isinstance(tid, int) and tid in tasks:
                return tasks.pop(tid)
            self.note(4, f"task {tid} already joined or unknown")
            return None
        # W18: cooperative task cancellation. The sequential engine runs
        # worker bodies inline at spawn time, so by the time a cancel can
        # name a task that task has already finished; the flag surface
        # still exists and answers with the same notes as the concurrent
        # engine's late-cancel path. Timing shapes are Rust-lane evidence
        # (tests/timing/, excluded from both walkers).
        if name == "cancel":
            tid = args[0] if args else None
            if not isinstance(tid, int) or tid <= 0:
                self.note(4, "cancel() needs a task id")
                return False
            tasks = getattr(self, "tasks", {})
            tombs = getattr(self, "task_tombstones", {})
            if tid in tasks or tid in tombs:
                self.note(4, f"task {tid} already finished")
                return False
            self.note(4, f"task {tid} unknown or already joined")
            return False
        if name == "task_state":
            tid = args[0] if args else None
            if tid == 0:
                return "done"
            if not isinstance(tid, int) or tid < 0:
                self.note(4, "task_state() needs a task id")
                return None
            tasks = getattr(self, "tasks", {})
            tombs = getattr(self, "task_tombstones", {})
            if tid in tasks or tid in tombs:
                return "done"
            self.note(4, f"task {tid} unknown or already joined")
            return None
        if name == "cancelled":
            return False
        # W15: task-group surface. The sequential engine's children are all
        # born finished, so wait_any answers the first LISTED id (completion
        # ordering is Rust-lane evidence in tests/timing/) and wait_all pops
        # every id in input order, position-aligned with the input.
        if name == "wait_all":
            ids = args[0] if args else []
            if not isinstance(ids, list):
                self.note(4, "wait_all() needs a list of task ids")
                return []
            tasks = getattr(self, "tasks", {})
            out = []
            for tid in ids:
                if isinstance(tid, int) and tid in tasks:
                    out.append(tasks.pop(tid))
                else:
                    self.note(4, f"task {tid} already joined or unknown")
                    out.append(None)
            return out
        if name == "wait_any":
            ids = args[0] if args else []
            if not isinstance(ids, list) or not ids:
                self.note(4, "wait_any() needs a list of task ids")
                return None
            tasks = getattr(self, "tasks", {})
            tombs = getattr(self, "task_tombstones", {})
            for tid in ids:
                if (isinstance(tid, int) and tid in tasks) or tid in tombs:
                    return tid
            self.note(4, "wait_any timeout (30000 ms); no task finished")
            return None
        # ---- W015: channels + select (builtins only, W036 grammar freeze).
        # The sequential oracle mirrors the concurrent engine op-for-op on
        # the buffered path; a program that would block raises the
        # oracle-only `blocked` stress (the Rust core blocks under fuel),
        # which the differential corpus never triggers by construction.
        if name == "channel":
            return Channel()
        if name == "send":
            ch = args[0] if args else None
            if not isinstance(ch, Channel) or len(args) < 2:
                raise Stress("unfolded", "send(ch, v) needs a channel and a value")
            v = args[1]
            # membrane first, then the depth pre-flight, then closed (the
            # Rust order: a handle payload is refused even on a closed chan)
            if isinstance(v, (Gene, SeqObj, ObjInst, Channel, WeakRef)):
                raise Stress("membrane",
                             f"send() refuses a {type_name(v)} payload; channels carry data, not handles")
            _stack = [(v, 0)]
            while _stack:
                _item, _d = _stack.pop()
                if _d > 100_000:
                    raise Stress("overflow", "send payload nesting too deep")
                if isinstance(_item, list):
                    _stack.extend((x, _d + 1) for x in _item)
                elif isinstance(_item, dict):
                    # Z-MAPORDER: the depth pre-walk sees BOTH stores
                    _stack.extend((x, _d + 1) for x in _map_values(_item))
            if ch.closed:
                raise Stress("closed_channel", "send on a closed channel")
            ch.buf.append(channel_wire(v))
            return None
        if name == "recv":
            ch = args[0] if args else None
            if not isinstance(ch, Channel):
                raise Stress("unfolded", "recv(ch) needs a channel")
            if ch.buf:
                return ch.buf.pop(0)
            if ch.closed:
                return None  # closed AND empty is the only null recv produces
            raise Stress("blocked", "oracle cannot block on recv; buffered sends must precede recv")
        if name == "close":
            ch = args[0] if args else None
            if not isinstance(ch, Channel):
                raise Stress("unfolded", "close(ch) needs a channel")
            if ch.closed:
                self.note(4, "close of an already-closed channel")
                return None
            ch.closed = True
            return None
        if name == "select":
            for c in args:
                if not isinstance(c, Channel):
                    # split construction so the SQL needle never sees the
                    # language's select builtin sharing a line with an f-string
                    stress_head = "select() needs channels, got a "
                    raise Stress("unfolded", f"{stress_head}{type_name(c)}")
            if not args:
                self.note(4, "select() with no channels; -1")
                return -1
            # strict declaration order: the leftmost ready channel wins
            for i, c in enumerate(args):
                if c.buf:
                    return i
            if all(c.closed for c in args):
                return -1
            raise Stress("blocked", "oracle cannot block on select; buffered sends must precede select")
        # ---- math
        if name == "floor":
            v = args[0] if args else 0
            if isinstance(v, float):
                import math as _m
                if not _m.isfinite(v) or v >= 9.223372036854776e18 or v <= -9.223372036854776e18:
                    raise Stress("overflow", "float too large for floor/ceil to int")
                return int(_m.floor(v))
            return v if isinstance(v, int) else 0
        if name == "ceil":
            v = args[0] if args else 0
            if isinstance(v, float):
                import math as _m
                if not _m.isfinite(v) or v >= 9.223372036854776e18 or v <= -9.223372036854776e18:
                    raise Stress("overflow", "float too large for floor/ceil to int")
                return int(_m.ceil(v))
            return v if isinstance(v, int) else 0
        if name == "sqrt":
            # F1 (S4-5): type-abuse parity — the Rust core routes sqrt
            # through the shared numeric checker: a non-numeric argument
            # (bools and numeric STRINGS included) is a contained unfolded
            # stress naming the type pair ("... found <t> and int" — the int
            # is sqrt's phantom second operand in the shared checker). Bare
            # float() swallowed "2.5"/bools silently and crashed raw on "x"
            # (rc=1 ValueError). Zero args stays 0.0 (rust: no arity stress
            # on sqrt()).
            v0 = args[0] if args else 0.0
            if isinstance(v0, bool) or not isinstance(v0, (int, float)):
                raise Stress("unfolded", f"numeric op needs numbers, found {type_name(v0)} and int")
            v = float(v0)
            if v < 0:
                raise Stress("unfolded", "sqrt of negative number")
            return v ** 0.5
        if name == "pow":
            # mirror the Rust builtin exactly: arity < 2 → note + the
            # (0.0, 0.0) fallback → 1.0 (rust DISCARDS provided args in the
            # fallback — pow(2) is 1.0, not 2.0); type abuse → the shared
            # checker wording IN OPERAND ORDER ("found int and str" for
            # pow(2, "x")); semantics = raw f64 powf (NO overflow stress —
            # the builtin returns inf), so 0**neg = inf and negative-base
            # fractional = nan via the mirror (S4-5/F1b class: python
            # raised raw errors / leaked a complex here).
            if len(args) < 2:
                self.note(4, "pow(x, y) needs two numbers; 0")
                return 1.0
            a0, b0 = args[0], args[1]
            if isinstance(a0, bool) or not isinstance(a0, (int, float)) or isinstance(b0, bool) or not isinstance(b0, (int, float)):
                raise Stress("unfolded", f"numeric op needs numbers, found {type_name(a0)} and {type_name(b0)}")
            return self._f64_powf(float(a0), float(b0))
        if name in ("re_match", "re_find", "re_groups"):
            import re as _re
            pat = args[0] if args else ""
            subj = args[1] if len(args) > 1 else ""
            try:
                rx = _re.compile(pat)
            except _re.error as e:
                raise Stress("unfolded", f"regex: {e}")
            try:
                if name == "re_match":
                    # prefix match (anchored at 0), mirroring the Rust core
                    return rx.match(subj) is not None
                start = int(args[2]) if len(args) > 2 else 0
                m = rx.search(subj, start)
                if m is None:
                    return None
                if name == "re_groups":
                    return [g if g is not None else None for g in m.groups()]
                return {"text": m.group(0), "start": m.start(), "end": m.end(),
                        "groups": [g if g is not None else None for g in m.groups()]}
            except _re.error as e:
                raise Stress("unfolded", f"regex: {e}")
            except RecursionError:
                raise Stress("overflow", "regex backtracking exceeded 2M steps")
        if name == "re_replace":
            # dx-r6 mirror of the Rust implementation: global literal
            # substitution (empty patterns behave like Python re.sub)
            import re as _re
            pat = args[0] if args else ""
            subj = args[1] if len(args) > 1 else ""
            repl = args[2] if len(args) > 2 else ""
            try:
                rx = _re.compile(pat)
            except _re.error as e:
                raise Stress("unfolded", f"regex: {e}")
            # literal replacement: a callable repl treats the text as data
            # (no \1 backref interpretation, mirrors the Rust implementation)
            return rx.sub(lambda _m: repl, subj)
        if name == "unix_time":
            import time as _t
            return int(_t.time())
        if name == "date_parts":
            import time as _t
            ts = int(args[0]) if args else 0
            st = _t.gmtime(ts)
            return {"year": st.tm_year, "month": st.tm_mon, "day": st.tm_mday,
                    "hour": st.tm_hour, "min": st.tm_min, "sec": st.tm_sec,
                    "wday": (st.tm_wday + 1) % 7}
        if name == "date_fmt":
            import time as _t
            ts = int(args[0]) if args else 0
            fmt = args[1] if len(args) > 1 else "%Y-%m-%d %H:%M:%S"
            st = _t.gmtime(ts)
            out = []
            i = 0
            while i < len(fmt):
                if fmt[i] == "%" and i + 1 < len(fmt):
                    c = fmt[i + 1]
                    out.append({"Y": f"{st.tm_year:04d}", "m": f"{st.tm_mon:02d}",
                                "d": f"{st.tm_mday:02d}", "H": f"{st.tm_hour:02d}",
                                "M": f"{st.tm_min:02d}", "S": f"{st.tm_sec:02d}",
                                "%": "%"}.get(c, "%" + c))
                    i += 2
                else:
                    out.append(fmt[i])
                    i += 1
            return "".join(out)
        if name in ("grapheme_len", "fold_case", "char_at", "char_slice"):
            # W28 (SPEC §3): Unicode depth, documented subsets, mirror of
            # the Rust core (identical rule set and fold table).
            s = v_display(args[0]) if args else ""
            if name == "grapheme_len":
                return grapheme_count(s)
            if name == "fold_case":
                out = []
                for ch in s:
                    cp = ord(ch)
                    if 0x41 <= cp <= 0x5A or 0xC0 <= cp <= 0xD6 or 0xD8 <= cp <= 0xDE:
                        cp += 32
                    elif 0x100 <= cp <= 0x137 and cp % 2 == 0:
                        cp += 1
                    elif 0x391 <= cp <= 0x3A9 and cp != 0x3A2:
                        cp += 32
                    out.append(chr(cp))
                return "".join(out)
            chars = list(s)
            n = len(chars)
            if name == "char_at":
                i = args[1] if len(args) > 1 else 0
                if not isinstance(i, int):
                    raise Stress("unfolded", "char_at(s, i) needs an int index")
                j = n + i if i < 0 else i
                if 0 <= j < n:
                    return chars[j]
                self.note(4, "char_at out of range; null")
                return None
            # char_slice
            i = args[1] if len(args) > 1 else 0
            j = args[2] if len(args) > 2 else 0
            a = max(0, min(n, n + i if i < 0 else i))
            b = max(0, min(n, n + j if j < 0 else j))
            return "".join(chars[a:max(a, b)])
        if name in ("norm_nfc", "norm_nfd", "casefold", "char_category"):
            # W28 stage 2 (SPEC §3): normalization, full case folding,
            # categories. The Rust core runs GENERATED tables (emitted from
            # THIS stdlib module by scripts/gen_unicode_tables.py), here the
            # stdlib is called directly, both cores agree by construction.
            # Non-string argument = the standard `unfolded` type family,
            # byte-matching the Rust core.
            if not args or not isinstance(args[0], str):
                raise Stress("unfolded", f"{name}(s) needs a string")
            s = args[0]
            if name == "norm_nfc":
                return unicodedata.normalize("NFC", s)
            if name == "norm_nfd":
                return unicodedata.normalize("NFD", s)
            if name == "casefold":
                return s.casefold()
            # char_category: ONE pinned shape, string in, the two-letter
            # general category of its FIRST CHAR out; empty string is the
            # soft tier (null + note), mirroring char_at's out-of-range tier.
            if not s:
                self.note(4, "char_category of empty string; null")
                return None
            return unicodedata.category(s[0])
        # ------------------------------------------------ Option / Result (W06, D-014)
        # Constructors + predicates + extraction. Error messages byte-match
        # the Rust core (Stress::at texts); families are distinct.
        if name == "some":
            if len(args) != 1:
                raise Stress("unfolded", "some(v) needs exactly 1 argument")
            return Variant("Some", args[0])
        if name == "none":
            if args:
                raise Stress("unfolded", "none() takes no arguments")
            return Variant("None", None)
        if name == "ok":
            if len(args) != 1:
                raise Stress("unfolded", "ok(v) needs exactly 1 argument")
            return Variant("Ok", args[0])
        if name == "err":
            if len(args) != 1:
                raise Stress("unfolded", "err(e) needs exactly 1 argument")
            return Variant("Err", args[0])
        if name == "is_some":
            return isinstance(args[0] if args else None, Variant) and args[0].tag == "Some"
        if name == "is_none":
            return isinstance(args[0] if args else None, Variant) and args[0].tag == "None"
        if name == "is_ok":
            return isinstance(args[0] if args else None, Variant) and args[0].tag == "Ok"
        if name == "is_err":
            return isinstance(args[0] if args else None, Variant) and args[0].tag == "Err"
        if name == "unwrap_or":
            if len(args) != 2:
                raise Stress("unfolded", "unwrap_or(v, default) needs exactly 2 arguments")
            v = args[0]
            # W06 parity fix: a null payload is a real payload, unwrap_or on
            # Ok(null)/Some(null) returns null, not the default (Rust parity)
            if isinstance(v, Variant) and v.tag in ("Some", "Ok"):
                return v.payload
            return args[1]
        if name == "unwrap":
            if len(args) != 1:
                raise Stress("unfolded", "unwrap(v) needs exactly 1 argument")
            v = args[0]
            if isinstance(v, Variant):
                if v.tag in ("Some", "Ok"):
                    # W06 parity fix: unwrap(Ok(null)) returns null, the Rust
                    # core stores ok(null) as Some(Null) and unwraps to it;
                    # the old payload-is-None guard raised here instead
                    return v.payload
                raise Stress("unwrap", f"unwrap on {v.tag}")
            raise Stress("unwrap", f"unwrap on a plain {type_name(v)} value")
        # ---- try_* family (W06 stage 2): Result-returning variants of the
        # failure-prone core builtins; err payload = message Str. The
        # messages must match the Rust core byte-for-byte (stdout-visible).
        if name == "try_num":
            if len(args) != 1:
                raise Stress("unfolded", "try_num(s) needs exactly 1 argument")
            v = args[0]
            if isinstance(v, bool):
                return Variant("Err", "num() failed: cannot parse bool as a number")
            if isinstance(v, (int, float)):
                return Variant("Ok", v)
            if isinstance(v, str):
                t = v.strip()
                try:
                    return Variant("Ok", int(t))
                except ValueError:
                    try:
                        return Variant("Ok", float(t))
                    except ValueError:
                        return Variant("Err", f"num('{v}') failed")
            return Variant("Err", f"num() failed: cannot parse {type_name(v)} as a number")
        if name == "try_index":
            if len(args) != 2:
                raise Stress("unfolded", "try_index(l, i) needs exactly 2 arguments")
            l, i = args[0], args[1]
            if not isinstance(l, list):
                return Variant("Err", f"try_index needs a list, got {type_name(l)}")
            if not isinstance(i, int) or isinstance(i, bool):
                return Variant("Err", f"index needs an int, got {type_name(i)}")
            if i < 0 or i >= len(l):
                return Variant("Err", f"index {i} out of range for list of length {len(l)}")
            return Variant("Ok", l[i])
        if name == "try_get":
            if len(args) != 2:
                raise Stress("unfolded", "try_get(m, k) needs exactly 2 arguments")
            m, k = args[0], args[1]
            if not isinstance(m, dict):
                return Variant("Err", f"try_get needs a map, got {type_name(m)}")
            # Z-MAPORDER: first-match lookup across BOTH stores (the
            # MapStore position law; the old m.items() walk missed the tail)
            hit = _map_lookup(m, k)
            if hit is not _MAP_MISS:
                return Variant("Ok", hit)
            return Variant("Err", f"no key '{v_display(k)}'")
        if name == "try_pop":
            if len(args) != 1:
                raise Stress("unfolded", "try_pop(l) needs exactly 1 argument")
            l = args[0]
            if not isinstance(l, list):
                return Variant("Err", f"try_pop needs a list, got {type_name(l)}")
            if not l:
                return Variant("Err", "pop from an empty list")
            return Variant("Ok", l.pop())
        # ---- try_* wave 2 (W06 stage 2, v2.7.0): extraction, environment
        # and parsing families. Same law as wave 1: Result-returning
        # ADDITIONS, legacy null/stress contracts stay pinned. Err payloads
        # are engine-neutral by construction — raw-input echoes or fixed
        # strings, never the underlying engine's parse-error text.
        if name == "try_first":
            if len(args) != 1:
                raise Stress("unfolded", "try_first(v) needs exactly 1 argument")
            v = args[0]
            if isinstance(v, list):
                if not v:
                    return Variant("Err", "first of an empty list")
                return Variant("Ok", v[0])
            if isinstance(v, str):
                if not v:
                    return Variant("Err", "first of an empty string")
                return Variant("Ok", v[0])
            return Variant("Err", f"first of a {type_name(v)}")
        if name == "try_last":
            if len(args) != 1:
                raise Stress("unfolded", "try_last(v) needs exactly 1 argument")
            v = args[0]
            if isinstance(v, list):
                if not v:
                    return Variant("Err", "last of an empty list")
                return Variant("Ok", v[-1])
            if isinstance(v, str):
                if not v:
                    return Variant("Err", "last of an empty string")
                return Variant("Ok", v[-1])
            return Variant("Err", f"last of a {type_name(v)}")
        if name == "try_char_at":
            if len(args) != 2:
                raise Stress("unfolded", "try_char_at(s, i) needs exactly 2 arguments")
            s = v_display(args[0])
            i = args[1]
            if not isinstance(i, int) or isinstance(i, bool):
                return Variant("Err", f"char_at needs an int index, got {type_name(i)}")
            chars = list(s)
            j = len(chars) + i if i < 0 else i
            if 0 <= j < len(chars):
                return Variant("Ok", chars[j])
            return Variant("Err", f"char_at index {i} out of range for string of length {len(chars)}")
        if name == "try_env":
            if len(args) != 1:
                raise Stress("unfolded", "try_env(name) needs exactly 1 argument")
            nm = v_display(args[0])
            self.cap_check("env", "env", nm)
            if nm in os.environ:
                return Variant("Ok", os.environ[nm])
            return Variant("Err", f"env '{nm}' is not set")
        if name == "try_json_parse":
            if len(args) != 1:
                raise Stress("unfolded", "try_json_parse(s) needs exactly 1 argument")
            s = v_display(args[0])
            try:
                return Variant("Ok", _json.loads(s, object_pairs_hook=lambda pairs: dict(pairs)))
            except ValueError:
                return Variant("Err", f"json_parse('{s}') failed")
        if name == "try_re_groups":
            if len(args) != 2:
                raise Stress("unfolded", "try_re_groups(pat, s) needs exactly 2 arguments")
            import re as _re
            pat = v_display(args[0])
            subj = v_display(args[1])
            try:
                rx = _re.compile(pat)
            except _re.error:
                return Variant("Err", f"re_groups('{pat}') failed")
            try:
                m = rx.search(subj, 0)
                if m is None:
                    return Variant("Err", "no match")
                return Variant("Ok", [g for g in m.groups()])
            except RecursionError:
                raise Stress("overflow", "regex backtracking exceeded 2M steps")
        # ---- W006-B: wave-3 IO try_ family (RESULT-WAVE3 §2c) — mirrors the
        # Rust arms: re-dispatch the legacy arm (behavior identical by
        # construction), map ONLY missing to the fixed engine-neutral payload;
        # interference (containment), overflow and arity unfolded stresses
        # stay stresses: a malformed call is not an expected failure (§2a).
        if name == "try_read_file":
            if len(args) != 1:
                raise Stress("unfolded", "try_read_file(path) needs exactly 1 argument")
            path = v_display(args[0]) if args else ""
            try:
                return Variant("Ok", self.builtin(env, "read_file", args))
            except Stress as e:
                if e.kind == "missing":
                    return Variant("Err", f"read_file '{path}' failed")
                raise
        if name == "try_read_file_bytes":
            if len(args) != 1:
                raise Stress("unfolded", "try_read_file_bytes(path) needs exactly 1 argument")
            path = v_display(args[0]) if args else ""
            try:
                return Variant("Ok", self.builtin(env, "read_file_bytes", args))
            except Stress as e:
                if e.kind == "missing":
                    return Variant("Err", f"read_file_bytes '{path}' failed")
                raise
        if name == "try_read_dir":
            if len(args) != 1:
                raise Stress("unfolded", "try_read_dir(path) needs exactly 1 argument")
            path = v_display(args[0]) if args else ""
            try:
                return Variant("Ok", self.builtin(env, "read_dir", args))
            except Stress as e:
                if e.kind == "missing":
                    return Variant("Err", f"read_dir '{path}' failed")
                raise
        if name == "try_run":
            if len(args) != 1:
                raise Stress("unfolded", "try_run(prog) needs exactly 1 argument")
            prog = v_display(args[0]) if args else ""
            try:
                return Variant("Ok", self.builtin(env, "run", args))
            except Stress as e:
                if e.kind == "missing":
                    return Variant("Err", f"run '{prog}' failed")
                raise
        if name == "try_http_get":
            if len(args) != 3:
                raise Stress("unfolded", "try_http_get(host, port, path) needs exactly 3 arguments")
            try:
                return Variant("Ok", self.builtin(env, "http_get", args))
            except Stress as e:
                # fixed payload, NO target echo (contract §2c fixes the shape)
                if e.kind == "missing":
                    return Variant("Err", "http_get failed")
                raise
        if name == "try_str_from_bytes":
            if len(args) != 1:
                raise Stress("unfolded", "try_str_from_bytes(b) needs exactly 1 argument")
            b = args[0]
            if not isinstance(b, (bytes, bytearray)):
                # type abuse follows the wave-2 family precedent (try_index):
                # inspectable Err, not a stress. Byte index N = offset of the
                # first invalid byte (UnicodeDecodeError.start == Rust
                # valid_up_to), deterministic both engines.
                return Variant("Err", f"try_str_from_bytes needs bytes, got {type_name(b)}")
            try:
                return Variant("Ok", b.decode("utf-8"))
            except UnicodeDecodeError as e:
                return Variant("Err", f"str_from_bytes: invalid UTF-8 at byte {e.start}")
        if name == "random":
            x = self.rng
            x ^= (x >> 12) & 0xFFFFFFFFFFFFFFFF
            x ^= (x << 25) & 0xFFFFFFFFFFFFFFFF
            x ^= (x >> 27) & 0xFFFFFFFFFFFFFFFF
            self.rng = x & 0xFFFFFFFFFFFFFFFF
            x = self.rng
            if args and isinstance(args[0], int) and not isinstance(args[0], bool) and args[0] > 0:
                r = (x * 0x2545F4914F6CDD1D) & 0xFFFFFFFFFFFFFFFF
                return r % args[0]
            return ((x >> 11) & ((1 << 53) - 1)) / 9007199254740992.0
        if name == "randomize":
            s = 0x9E3779B97F4A7C15
            if args and isinstance(args[0], (int, float)) and not isinstance(args[0], bool):
                s = int(args[0]) & 0xFFFFFFFFFFFFFFFF
            self.rng = s if s != 0 else 0x9E3779B97F4A7C15
            return None
        if name == "promoter_telemetry":
            # loop-9 (F-3): per-gene promoter attempt telemetry (mirror)
            nm = v_display(args[0]) if args else ""
            attempts, on_total, episodes = self.promoter_tel.get(nm, (0, 0, 0))
            on_frac = (on_total / attempts) if attempts > 0 else 0.0
            burst_size = (on_total / episodes) if episodes > 0 else 0.0
            return {"attempts": attempts, "on_total": on_total, "episodes": episodes,
                    "on_frac": on_frac, "burst_size": burst_size}
        if name == "burst_set":
            # loop-9 (R9): runtime promoter-rate modulation (mirror)
            nm = v_display(args[0]) if args else ""
            if len(args) >= 3 and isinstance(args[1], (int, float)) and isinstance(args[2], (int, float)):
                kon = min(max(float(args[1]), 0.0), 1.0)
                koff = min(max(float(args[2]), 0.0), 1.0)
                self.burst_overrides[nm] = (kon, koff)
                if not self.methyl_quiet:
                    self.note(1, f"burst override: '{nm}' (kon={kon!r}, koff={koff!r})")
                return {"kon": kon, "koff": koff}
            self.burst_overrides.pop(nm, None)
            if not self.methyl_quiet:
                self.note(1, f"burst override cleared: '{nm}'")
            return None
        if name == "expr_on":
            # reg-bio (F-1): mirror of the Rust builtin, in-source switch for
            # the telegraph promoter layer (kon/koff clamped 0..1)
            kon = 0.3
            koff = 0.1
            if args and isinstance(args[0], (int, float)) and not isinstance(args[0], bool):
                kon = min(max(float(args[0]), 0.0), 1.0)
            if len(args) > 1 and isinstance(args[1], (int, float)) and not isinstance(args[1], bool):
                koff = min(max(float(args[1]), 0.0), 1.0)
            self.expr_stochastic = True
            self.expr_kon = kon
            self.expr_koff = koff
            self.note(1, f"telegraph promoter on (kon={kon}, koff={koff})")
            return True
        if name == "expr_off":
            self.expr_stochastic = False
            return False
        if name == "decay_clock":
            # reg-bio-2 (C2): mirror of the Rust builtin, in-source switch
            # for the decay clock (interval n, optional fraction f)
            n = None
            if args and isinstance(args[0], (int, float)) and not isinstance(args[0], bool) and args[0] > 0:
                n = int(args[0])
            frac = None
            if len(args) > 1 and isinstance(args[1], (int, float)) and not isinstance(args[1], bool):
                frac = min(max(float(args[1]), 0.0), 1.0)
            self.decay_clock_n = n
            self.decay_clock_f = frac
            if n is not None:
                self.note(1, f"decay clock on (one decay step every {n} calls)")
                return True
            self.note(1, "decay clock off (event-driven)")
            return False
        # ---- ligands (reg-bio-2 A4)
        if name == "ligand_set":
            nm = v_display(args[0]) if args else ""
            v = 0.0
            if len(args) > 1 and isinstance(args[1], (int, float)) and not isinstance(args[1], bool):
                v = min(max(float(args[1]), 0.0), 1.0)
            if nm not in self.ligands:
                self.ligands.append(nm)
            self.ligand_pools[nm] = v
            self.note(1, f"ligand pool '{nm}': {v}")
            return v
        if name == "ligand":
            nm = v_display(args[0]) if args else ""
            return self._ligand_level(nm)
        if name == "secrete":
            # loop-9 (C8): mirror of the Rust secrete, Int exact, Float
            # floors (never rounds), negative clamps to 0 with a note,
            # non-finite clamps to 0, saturating add capped at 1e9.
            nm = v_display(args[0]) if args else ""
            amt = 1
            if len(args) > 1:
                a = args[1]
                if isinstance(a, bool):
                    amt = 1
                elif isinstance(a, int):
                    if a < 0:
                        self.note(4, f"secrete: negative amount clamps to 0 molecules ('{nm}')")
                    amt = max(0, min(a, 1_000_000_000))
                elif isinstance(a, float):
                    if a != a or a in (float("inf"), float("-inf")):
                        self.note(4, f"secrete: non-finite amount clamps to 0 molecules ('{nm}')")
                        amt = 0
                    else:
                        if a < 0.0:
                            self.note(4, f"secrete: negative amount floors to 0 molecules ('{nm}')")
                        amt = int(min(max(math.floor(a), 0.0), 1e9))
                else:
                    amt = 1
            committed = 0
            if self._signal_register(nm):
                cur = self.medium.get(nm, 0)
                nxt = min(cur + amt, 1_000_000_000)
                self.medium[nm] = nxt
                committed = nxt - cur
            self.note(1, f"secrete '{nm}': +{committed} molecules (level {fmt_float(committed / 1e9)})")
            return committed
        if name == "quorum":
            # loop-9 (C8): mirror, one arg -> level; two args -> level >= t.
            nm = v_display(args[0]) if args else ""
            lvl = self._signal_level(nm)
            if len(args) > 1:
                t = args[1]
                if isinstance(t, bool):
                    t = 0.0
                elif isinstance(t, (int, float)):
                    t = float(t)
                else:
                    t = 0.0
                return lvl >= t
            return lvl
        if name == "quench":
            # loop-9 (C8): mirror, m <- floor(m * (1-f)); no arg destroys all.
            nm = v_display(args[0]) if args else ""
            f = 1.0
            if len(args) > 1:
                a = args[1]
                if isinstance(a, bool):
                    f = 1.0
                elif isinstance(a, (int, float)):
                    f = min(max(float(a), 0.0), 1.0)
                else:
                    f = 1.0
            cur = self.medium.get(nm, 0)
            nxt = int(math.floor(cur * (1.0 - f)))
            self.medium[nm] = nxt
            removed = cur - nxt
            self.note(1, f"quench '{nm}': -{removed} molecules")
            return removed
        if name == "quorum_state":
            # loop-9 (C8): mirror, sorted-key species -> molecule counts.
            return {k: self.medium[k] for k in sorted(self.medium)}
        if name == "chr":
            i = args[0] if args and isinstance(args[0], int) else 0
            return chr(i) if 0 <= i <= 0x10FFFF else ""
        if name == "ord":
            s = args[0] if args and isinstance(args[0], str) else ""
            return ord(s[0]) if s else 0
        if name == "sleep":
            import time as _t
            ms = 0
            if args and isinstance(args[0], (int, float)):
                ms = max(args[0], 0)
            _t.sleep(ms / 1000.0)
            return None
        if name == "argv":
            return list(self.cli_args)
        # ---- filesystem (capability-gated)
        if name == "read_file":
            path = v_display(args[0]) if args else ""
            self.cap_check("read", "read", path)
            try:
                with open(path, "r", encoding="utf-8", errors="strict") as f:
                    return f.read()
            except OSError as e:
                raise Stress("missing", f"read_file '{path}': {io_err(e)}")
        if name == "write_file":
            path = v_display(args[0]) if args else ""
            body = v_display(args[1]) if len(args) > 1 else ""
            self.cap_check("write", "write", path)
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(body)
                return True
            except OSError as e:
                raise Stress("missing", f"write_file '{path}': {io_err(e)}")
        if name == "append_file":
            path = v_display(args[0]) if args else ""
            body = v_display(args[1]) if len(args) > 1 else ""
            self.cap_check("write", "write", path)
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(body)
                return True
            except OSError as e:
                raise Stress("missing", f"append_file '{path}': {io_err(e)}")
        # ---- W029: bytes file I/O (same capability gates as the text forms)
        if name == "read_file_bytes":
            path = v_display(args[0]) if args else ""
            self.cap_check("read", "read", path)
            try:
                with open(path, "rb") as f:
                    return f.read()
            except OSError as e:
                raise Stress("missing", f"read_file_bytes '{path}': {io_err(e)}")
        if name == "write_file_bytes":
            path = v_display(args[0]) if args else ""
            body = args[1] if len(args) > 1 else b""
            if isinstance(body, str):
                body = body.encode("utf-8")
            elif not isinstance(body, bytes):
                raise Stress("unfolded", f"write_file_bytes needs bytes (or str), got {type_name(body)}")
            self.cap_check("write", "write", path)
            try:
                with open(path, "wb") as f:
                    f.write(body)
                return True
            except OSError as e:
                raise Stress("missing", f"write_file_bytes '{path}': {io_err(e)}")
        if name == "exists":
            path = v_display(args[0]) if args else ""
            self.cap_check("read", "read", path)
            return os.path.exists(path)
        if name == "file_size":
            path = v_display(args[0]) if args else ""
            self.cap_check("read", "read", path)
            try:
                return os.path.getsize(path)
            except OSError:
                return -1
        if name == "read_dir":
            path = v_display(args[0]) if args else ""
            self.cap_check("read", "read", path)
            try:
                return sorted(os.listdir(path))
            except OSError as e:
                raise Stress("missing", f"read_dir '{path}': {io_err(e)}")
        # ---- dx-r6: fs mutate ops (mirror of the Rust capability discipline)
        if name == "fs_delete":
            path = v_display(args[0]) if args else ""
            self.cap_check("write", "write", path)
            if os.path.islink(path):
                raise Stress("interference", f"fs_delete '{path}': refused, path is a symlink")
            try:
                if os.path.isdir(path):
                    os.rmdir(path)  # empty dirs only: no recursive bombs
                else:
                    os.remove(path)
                return True
            except OSError as e:
                raise Stress("missing", f"fs_delete '{path}': {io_err(e)}")
        if name == "fs_rename":
            src = v_display(args[0]) if args else ""
            dst = v_display(args[1]) if len(args) > 1 else ""
            self.cap_check("write", "write", src)
            self.cap_check("write", "write", dst)
            try:
                os.rename(src, dst)
                return True
            except OSError as e:
                raise Stress("missing", f"fs_rename '{src}' -> '{dst}': {io_err(e)}")
        if name == "fs_mkdir":
            path = v_display(args[0]) if args else ""
            self.cap_check("write", "write", path)
            try:
                os.makedirs(path, exist_ok=True)
                return True
            except OSError as e:
                raise Stress("missing", f"fs_mkdir '{path}': {io_err(e)}")
        # ---- process / net (capability-gated)
        if name == "run":
            prog = v_display(args[0]) if args else ""
            pargs = [v_display(x) for x in args[1]] if len(args) > 1 and isinstance(args[1], list) else []
            self.cap_check("run", "run", prog)
            import subprocess as _sp
            try:
                cp = _sp.run([prog] + pargs, capture_output=True, text=True)
                return {"code": cp.returncode, "stdout": cp.stdout, "stderr": cp.stderr, "ok": cp.returncode == 0}
            except OSError as e:
                raise Stress("missing", f"run '{prog}': {io_err(e)}")
        if name == "http_get":
            host = v_display(args[0]) if args else ""
            port = int(args[1]) if len(args) > 1 and isinstance(args[1], int) else 80
            path = v_display(args[2]) if len(args) > 2 else "/"
            self.cap_check("net", "net", f"{host}:{port}")
            import socket as _s
            try:
                s = _s.create_connection((host, port), timeout=10)
                s.sendall(f"GET {path} HTTP/1.0\r\nHost: {host}\r\nUser-Agent: operon\r\n\r\n".encode())
                buf = b""
                while True:
                    chunk = s.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
                s.close()
                pos = buf.find(b"\r\n\r\n")
                return buf[pos + 4:].decode("utf-8", "replace") if pos >= 0 else buf.decode("utf-8", "replace")
            except OSError as e:
                raise Stress("missing", f"http_get '{host}:{port}': {io_err(e)}")
        if name in ("serve", "recv_request", "send_response"):
            # the sequential oracle does not host a server. serve stays the
            # honest stub (a real bind is Rust-runner-only surface, the same
            # class as repressi_start's wall-clock thread). recv_request's
            # empty-queue null IS the faithful rust surface. send_response is
            # mirrored FAITHFULLY (S3: the coverage audit caught the old
            # null-stub diverging on both reachable surfaces).
            if name == "serve":
                port = int(args[0]) if args and isinstance(args[0], int) else 8080
                self.cap_check("net", "net", f"127.0.0.1:{port}")
                self.note(4, f"{name} is not available in the sequential oracle; null")
                return None
            if name == "recv_request":
                self.note(4, f"{name} is not available in the sequential oracle; null")
                return None
            # send_response mirror (rust interp.rs arm): header-safety check
            # FIRST, then the conn dispatch — with no server, the only
            # reachable outcome is 'server not running'.
            conn = args[0] if args and isinstance(args[0], int) else 0
            status = v_display(args[1]) if len(args) > 1 else "200"
            ctype = v_display(args[2]) if len(args) > 2 else "text/html"
            body = v_display(args[3]) if len(args) > 3 else ""
            if any(ord(c) < 0x20 or c == "\x7f" for c in status + ctype):
                raise Stress("interference", "send_response: status/content-type contain control characters (header injection refused)")
            raise Stress("missing", "send_response: server not running")
        # ---- json
        if name == "json_parse":
            s = v_display(args[0]) if args else "null"
            try:
                return _json.loads(s, object_pairs_hook=lambda pairs: dict(pairs))
            except ValueError as e:
                raise Stress("unfolded", f"json_parse: {e}")
        if name == "json_str":
            v = args[0] if args else None
            return self._json_str(v)
        # ---- W34 stage 2: phenotype serialization primitives (mirror of the
        # Rust arms: silent predicate + shallow field-map copy + wire-map
        # rebuild; the wire shape is the spawn boundary's field map + hidden
        # "#phenotype" key)
        if name == "is_object":
            return isinstance(args[0], ObjInst) if args else False
        if name == "object_fields":
            v = args[0] if args else None
            if isinstance(v, ObjInst):
                return dict(v.fields)
            self.note(4, f"object_fields({type_name(v)}) on a non-phenotype value; null")
            return None
        if name == "object_from_map":
            m = args[0] if args else None
            if not isinstance(m, dict):
                raise Stress("unfolded", f"object_from_map expects a map; got {type_name(m)}")
            # Z-MAPORDER: the identity probe and the field walk cover BOTH
            # stores (a promoted map carries tail entries too)
            tag = _map_member_get(m, "#phenotype")
            if tag is None or tag is _MAP_MISS:
                raise Stress("unfolded", 'object_from_map: map has no "#phenotype" identity key')
            decl = self.phenos.get(str(tag))
            if decl is None:
                raise Stress(
                    "unfolded",
                    f"object_from_map: phenotype '{tag}' not declared in this program",
                )
            return ObjInst(decl, {k: v for k, v in _map_items(m) if k != "#phenotype"})
        # ---- env (capability-gated)
        if name == "env":
            nm = v_display(args[0]) if args else ""
            self.cap_check("env", "env", nm)
            return os.environ.get(nm)
        # ---- py (substrate-r1): the Python ecosystem bridge. The oracle
        # runs in-process (it IS python); the ok/value/error/code contract
        # matches the Rust bridge. Timeout/env-scrub containment is not
        # mirrored here, the granted suite that exercises those paths is
        # Rust-runner-only, and the differential corpus avoids py effects.
        if name == "py":
            module = v_display(args[0]) if args else ""
            func = v_display(args[1]) if len(args) > 1 else ""
            call_args = args[2] if len(args) > 2 and isinstance(args[2], list) else []
            if not module:
                raise Stress("missing", "py: module name required")
            self.cap_check("py", "py", module)
            import importlib as _il
            try:
                mod = _il.import_module(module)
                obj = mod
                for part in str(func or "").split("."):
                    if part:
                        obj = getattr(obj, part)
                val = obj(*call_args)
                return {"ok": True, "value": val, "error": None, "code": 0}
            except BaseException as e:
                import traceback as _tb
                msg = "".join(_tb.format_exception_only(type(e), e)).strip()
                return {"ok": False, "value": None, "error": msg, "code": 1}
        if name == "call":
            # dynamic dispatch: call(name_or_gene, args_list)
            target = args[0] if args else None
            call_args = args[1] if len(args) > 1 and isinstance(args[1], list) else []
            if isinstance(target, str):
                if target in BUILTINS or target in BUILTIN_SYNONYMS:
                    return self.builtin(env, BUILTIN_SYNONYMS.get(target, target), call_args)
                tv = self.lookup(env, target)
                return self.call_value(env, tv, call_args)
            return self.call_value(env, target, call_args)
        # ---- L1a: iteration + numeric builtins (mirror src/interp.rs) ----
        if name == "enumerate":
            v = args[0] if args else None
            if isinstance(v, list):
                return [[i, x] for i, x in enumerate(v)]
            if isinstance(v, str):
                return [[i, c] for i, c in enumerate(v)]
            self.note(4, f"enumerate of a {type_name(v)}; null")
            return None
        if name == "zip":
            a = args[0] if args else None
            b = args[1] if len(args) > 1 else None
            if not isinstance(a, list) or not isinstance(b, list):
                self.note(4, "zip needs two lists; null")
                return None
            return [[a[i], b[i]] for i in range(min(len(a), len(b)))]
        if name == "sorted":
            v = args[0] if args else None
            if not isinstance(v, list):
                self.note(4, f"sorted of a {type_name(v)}; null")
                return None
            out = list(v)
            if len(args) > 1 and isinstance(args[1], Gene):
                # #137 (Z-137-SORTSTABLE): STABLE comparator sort — the same
                # walk the engine's comparator_sort runs for n <= 32 (swap iff
                # cmp(current, previous) strictly-before; ties stop the walk
                # and keep input order). Above 32 the engine switches to a
                # bottom-up merge with the same output for consistent
                # comparators; the walk mirrors its output byte-for-byte.
                cmp = args[1]
                for i in range(1, len(out)):
                    j = i
                    while j > 0:
                        before = truthy(self.call_value(env, cmp, [out[j], out[j - 1]]))
                        if before:
                            out[j - 1], out[j] = out[j], out[j - 1]
                            j -= 1
                        else:
                            break
            else:
                # identical key to the .sort() method, one ordering contract
                out.sort(key=lambda x: (
                    (0, float(x), "") if isinstance(x, (int, float)) and not isinstance(x, bool)
                    else ((0, float(int(x)), "") if isinstance(x, bool)
                          else ((1, 0.0, x) if isinstance(x, str)
                                else (2, 0.0, v_repr(x))))
                ))
            return out
        if name == "reversed":
            v = args[0] if args else None
            if isinstance(v, list):
                return list(reversed(v))
            self.note(4, f"reversed of a {type_name(v)}; null")
            return None
        if name == "any":
            v = args[0] if args else None
            if isinstance(v, list):
                return any(truthy(x) for x in v)
            self.note(4, f"any of a {type_name(v)}; false")
            return False
        if name == "all":
            v = args[0] if args else None
            if isinstance(v, list):
                return all(truthy(x) for x in v)
            self.note(4, f"all of a {type_name(v)}; false")
            return False
        if name == "first":
            v = args[0] if args else None
            if isinstance(v, list):
                if not v:
                    self.note(4, "first of an empty list; null")
                    return None
                return v[0]
            if isinstance(v, str):
                if not v:
                    self.note(4, "first of an empty string; null")
                    return None
                return v[0]
            self.note(4, f"first of a {type_name(v)}; null")
            return None
        if name == "last":
            v = args[0] if args else None
            if isinstance(v, list):
                if not v:
                    self.note(4, "last of an empty list; null")
                    return None
                return v[-1]
            if isinstance(v, str):
                if not v:
                    self.note(4, "last of an empty string; null")
                    return None
                return v[-1]
            self.note(4, f"last of a {type_name(v)}; null")
            return None
        if name == "take":
            v = args[0] if args else None
            n = args[1] if len(args) > 1 else None
            if not isinstance(n, int) or isinstance(n, bool):
                self.note(4, "take needs a count; null")
                return None
            if n < 0:
                n = 0
            if isinstance(v, list):
                return v[:n]
            if isinstance(v, str):
                return v[:n]
            self.note(4, f"take of a {type_name(v)}; null")
            return None
        if name == "drop":
            v = args[0] if args else None
            n = args[1] if len(args) > 1 else None
            if not isinstance(n, int) or isinstance(n, bool):
                self.note(4, "drop needs a count; null")
                return None
            if n < 0:
                n = 0
            if isinstance(v, list):
                return v[n:]
            if isinstance(v, str):
                return v[n:]
            self.note(4, f"drop of a {type_name(v)}; null")
            return None
        if name == "unique":
            v = args[0] if args else None
            if isinstance(v, list):
                out = []
                for x in v:
                    if not any(deep_eq(u, x) for u in out):
                        out.append(x)
                return out
            self.note(4, f"unique of a {type_name(v)}; null")
            return None
        if name == "flatten":
            v = args[0] if args else None
            if isinstance(v, list):
                out = []
                for x in v:
                    if isinstance(x, list):
                        out.extend(x)
                    else:
                        out.append(x)
                return out
            self.note(4, f"flatten of a {type_name(v)}; null")
            return None
        if name == "chunk":
            v = args[0] if args else None
            n = args[1] if len(args) > 1 else None
            if not isinstance(n, int) or isinstance(n, bool):
                self.note(4, "chunk needs a size; null")
                return None
            if n <= 0:
                self.note(4, "chunk size must be positive; empty")
                return []
            if isinstance(v, list):
                return [v[i:i + n] for i in range(0, len(v), n)]
            self.note(4, f"chunk of a {type_name(v)}; null")
            return None
        if name == "round":
            v = args[0] if args else None
            d = args[1] if len(args) > 1 else 0
            if not isinstance(d, int) or isinstance(d, bool):
                self.note(4, "digit count must be an int; treated as 0")
                d = 0
            if d < 0:
                self.note(4, "negative digit count; treated as 0")
                d = 0
            if isinstance(v, bool):
                self.note(4, f"round of a {type_name(v)}; 0")
                return 0
            if isinstance(v, int):
                return v
            if isinstance(v, float):
                if v != v or v in (float("inf"), float("-inf")):
                    return v
                scale = 10.0 ** d
                r = (abs(v) * scale + 0.5) // 1 / scale
                r = r if v >= 0 else -r
                if d == 0:
                    if not (-(2**63) <= r <= 2**63 - 1):
                        raise Stress("overflow", "float too large for round to int")
                    return int(r)
                return r
            self.note(4, f"round of a {type_name(v)}; 0")
            return 0
        if name == "clamp":
            v = args[0] if args else None
            lo = args[1] if len(args) > 1 else None
            hi = args[2] if len(args) > 2 else None
            nums = (int, float)
            if not (isinstance(v, nums) and not isinstance(v, bool)
                    and isinstance(lo, nums) and not isinstance(lo, bool)
                    and isinstance(hi, nums) and not isinstance(hi, bool)):
                self.note(4, "clamp needs three numbers; null")
                return None
            if v < lo:
                return lo
            if v > hi:
                return hi
            return v
        if name == "divmod":
            # parity by construction: reuses the // and % operators
            a = args[0] if args else None
            b = args[1] if len(args) > 1 else None
            q = self.binop("//", a, b)
            r = self.binop("%", a, b)
            return [q, r]
        self.note(4, f"unknown builtin '{name}'; null")
        return None

    @staticmethod
    def _json_str(v, _seen=None, _depth=0):
        # reg-r4: cycle-safe, repeated branch serializes as null, depth
        # cap 512 (mirror of the Rust json_stringify_g)
        from ..interp import Interp
        if _seen is None:
            _seen = set()
        if _depth > 512:
            return "null"
        if v is None: return "null"
        if v is True: return "true"
        if v is False: return "false"
        if isinstance(v, int): return str(v)
        if isinstance(v, float):
            # RFC 8259 honesty (SPEC §10): JSON has no NaN/Inf, non-finite
            # floats serialize as null, exactly like the Rust json_stringify_g
            # (display/print keep the nan/inf spelling via fmt_float; the WIRE
            # never carries them. Found by the std_serialize proof.)
            if v != v or v == float("inf") or v == float("-inf"):
                return "null"
            return fmt_float(v)
        if isinstance(v, str): return _json.dumps(v)
        # W029 mirror: JSON has no bytes type, the lossless view is the int
        # list (the Rust json_stringify_g Bytes arm).
        if isinstance(v, bytes):
            return "[" + ",".join(str(x) for x in v) + "]"
        if isinstance(v, (list, dict)):
            marker = id(v)
            if marker in _seen:
                return "null"
            _seen.add(marker)
            if isinstance(v, list):
                out = "[" + ",".join(Interp._json_str(x, _seen, _depth + 1) for x in v) + "]"
            else:
                # #214: BOTH stores; non-str keys render through v_repr (the
                # Rust json_stringify_g key law — container keys stringify
                # via the display form, e.g. {"[1, 2]":5}), never Python str()
                # (dict keys would render with Python quoting)
                out = "{" + ",".join(
                    _json.dumps(k if isinstance(k, str) else v_repr(k, _seen, _depth + 1))
                    + ":" + Interp._json_str(val, _seen, _depth + 1)
                    for k, val in _map_items(v)) + "}"
            _seen.discard(marker)
            return out
        # W06 (D-014) mirror: variants serialize as single-key objects,
        # {"some": v} / {"ok": v} / {"err": v}; None serializes as null.
        # Matches the Rust json_stringify_g Variant arms byte-for-byte.
        # W06 parity fix: a null payload is a real payload, ok(null)
        # serializes {"ok":null} on the Rust core; only tag None is bare null.
        if isinstance(v, Variant):
            if v.tag == "None":
                return "null"
            key = {"Some": "some", "Ok": "ok", "Err": "err"}.get(v.tag, "none")
            return "{" + _json.dumps(key) + ":" + Interp._json_str(v.payload, _seen, _depth + 1) + "}"
        return _json.dumps(v_display(v))

    def construct_obj(self, p, args, site_env=None):
        chain = []
        d = p
        hops = 0
        while d is not None and hops <= 32:
            chain.append(d)
            d = self.phenos.get(d.parent) if d.parent else None
            hops += 1
        fields = {}
        for dd in reversed(chain):
            for fname, fexpr in dd.fields:
                # z-s2-harden (#126.7): field inits evaluate at the new site
                # (was self.globals — construction-site locals invisible)
                fields[fname] = self.eval_expr(site_env if site_env is not None else self.globals, fexpr)
        obj = ObjInst(p, fields)
        # W04: trait contract check, required methods must be provided by
        # the lineage; a break is a NOTE (Total Grammar), never fatal.
        for tname in p.implements:
            t = self.traits.get(tname)
            if t is None:
                self.note(4, f"trait '{tname}' not declared; contract on '{p.name}' ignored")
                continue
            for req in t.methods:
                if not req.required:
                    continue
                provided = any(g.name == req.name for dd in chain for g in dd.methods)
                if not provided:
                    self.note(4, f"phenotype '{p.name}' implements '{tname}' but does not provide '{req.name}()'")
        for dd in reversed(chain):
            for g in dd.methods:
                if g.name == "init":
                    self.call_method_gene(g, obj, args)
                    break
            else:
                continue
            break
        return obj
