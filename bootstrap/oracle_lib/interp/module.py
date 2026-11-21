"""operon oracle: interp.module (split of bootstrap/oracle.py)."""

import contextlib
import os
from ..fmt import v_repr
from ..parser import parse
from ..values import BreakLoop, ContinueLoop, Return, Stress



class IModule:

    # ---- modules
    def load_module(self, path):
        if path in self.modules:
            return self.modules[path]
        if path in self.loading:
            return {}
        p = path if path.endswith(".op") else path + ".op"
        # W069: resolution chain mirrors genes.rs resolve_path, the
        # importing file's directory first, then CWD, then std/, then
        # $OPERON_STD. (Exe-relative roots are runtime-only: the oracle
        # never ships beside a std/ tree; see SPEC §8 table.)
        cands = [p, os.path.join("std", p)]
        if self.base_dir:
            cands.insert(0, os.path.join(self.base_dir, p))
        std_dir = os.environ.get("OPERON_STD")
        if std_dir:
            cands.append(os.path.join(std_dir, p))
        # W19/W23 mirror: root 7, vendored deps from the lockfile (the
        # leading path segment maps to the pinned checkout dir)
        for dep_name, dep_dir in self.lock_dirs:
            seg = dep_name + "/"
            if p == dep_name + ".op":
                cands.append(os.path.join(dep_dir, p))
            elif p.startswith(seg):
                cands.append(os.path.join(dep_dir, p[len(seg):]))
        resolved = next((c for c in cands if os.path.exists(c)), None)
        if resolved is None:
            # W025 stage 2: None = not found, distinct from an existing but
            # empty module ({}), so the nested-table descent can try the
            # next file prefix. The use arm binds {} for a total failure,
            # exactly as before.
            return None
        # #123 mirror: key the cache by the CANONICAL path — the same module
        # imported via two spellings (`use "h.op"` + `use "./h.op"`) must
        # load ONCE (the Rust side keys interp.modules by the canonicalized
        # path since the same fix landed there).
        canon_key = os.path.realpath(resolved)
        if canon_key in self.modules:
            return self.modules[canon_key]
        src = open(resolved, encoding="utf-8", errors="replace").read()  # W59: explicit UTF-8 (Windows locale default is cp1252)
        self.loading.append(path)
        stmts, notes, pubs = parse(src)
        for nt in notes:
            self.note(nt.rung, f"[{path}] {nt.message}")
        menv = self.new_scope(self.globals)
        for st in stmts:
            try:
                with contextlib.suppress(Return, BreakLoop, ContinueLoop):
                    self.exec_stmt(menv, st)
            except Stress as e:
                # W06 (D-014) mirror: propagation with no enclosing gene,
                # the variant value passes through (noted, never rejected).
                if e.prop is not None:
                    self.note(4, f"propagation reached top level: {v_repr(e.prop)} passes through")
                else:
                    self.note(4, f"stress contained: [{e.kind}] {e.message}")
        self.loading.pop()
        # export rule: anchor export wins, else top-level genes/lets.
        # W24 mirror: under .cell modules.visibility = strict, a module with
        # pub marks exports ONLY those names (anchors win when present); a
        # strict module with zero pub marks keeps default-open + a note.
        has_anchor = any(s[0] == "anchor_export" for s in stmts) or \
            any(s[0] == "tad" and any(x[0] == "anchor_export" for x in s[2]) for s in stmts)
        strict = str(self.cell.get("modules.visibility", "")).lower() == "strict"
        exports = {}
        if has_anchor:
            names = []
            for s in stmts:
                if s[0] == "anchor_export":
                    names.extend(s[1])
                if s[0] == "tad":
                    for x in s[2]:
                        if x[0] == "anchor_export":
                            names.extend(x[1])
            for nm in names:
                v = self.lookup(menv, nm)
                if v is not None or nm in menv:
                    exports[nm] = v
        elif strict and pubs:
            for nm in pubs:
                v = self.lookup(menv, nm)
                if v is not None or nm in menv:
                    exports[nm] = v
            hidden = sum(1 for kk in menv if isinstance(kk, str) and not kk.startswith("#")) - len(exports)
            if hidden > 0:
                self.note(4, f"strict visibility: {hidden} private name(s) hidden in '{path}' (mark with pub or anchor export)")
        else:
            if strict:
                self.note(4, f"strict visibility: '{path}' has no pub marks, default-open retained (add pub or anchor export)")
            for kk, vv in menv.items():
                # W24 fix (latent): tuple keys are internal const markers,
                # they are never exports (a module with `const` used to crash
                # this loop; found by the visibility differential fixture).
                if isinstance(kk, str) and kk != "__parent__" and not kk.startswith("#"):
                    exports[kk] = vv
        self.modules[canon_key] = exports
        return exports
