"""operon oracle: loader (split of bootstrap/oracle.py)."""

import contextlib
import os
from .bio import apply_rna, collect_structure
from .fmt import v_repr
from .interp import Interp
from .parser import parse
from .values import BreakLoop, ContinueLoop, Gene, M64, Return, Stress



def load_file(path, cell=None, variant=None, rna=None, args=None, caps=None):
    src = open(path, encoding="utf-8", errors="replace").read()  # W59: explicit UTF-8
    stem = os.path.basename(path).rsplit(".", 1)[0]
    it = Interp(cell=cell or {}, cli_args=args or [])
    # W069: entry file's directory = resolution root #1 (matches Rust
    # tools.rs interp.base_dir = entry-file dir).
    d = os.path.dirname(os.path.abspath(path))
    if d and d != os.path.abspath("."):
        it.base_dir = d
    # W19/W23 mirror: vendored dependency roots from the nearest
    # operon.lock (program dir, then CWD), resolution root 7.
    for lp in (os.path.join(d, "operon.lock"), "operon.lock"):
        try:
            with open(lp, encoding="utf-8") as f:
                lock_text = f.read()
            # tiny parse: name/rev pairs in [[dep]] blocks
            name = rev = None
            for raw in lock_text.splitlines():
                line = raw.strip()
                if line == "[[dep]]":
                    name = rev = None
                elif line.startswith("name") and "=" in line:
                    name = line.split("=", 1)[1].strip().strip('"')
                elif line.startswith("rev") and "=" in line:
                    rev = line.split("=", 1)[1].strip().strip('"')
                if name and rev:
                    dd = os.environ.get("OPERON_DEPS") or os.path.join(
                        os.path.expanduser("~"), ".operon", "deps")
                    it.lock_dirs.append((name, os.path.join(dd, "%s-%s" % (name, rev[:12]))))
                    name = rev = None
            break
        except OSError:
            continue
    if caps is not None:
        it.caps = caps
    if variant:
        it.cell["cli.variant"] = variant
    if rna:
        patch = open(rna, encoding="utf-8", errors="replace").read()  # W59: explicit UTF-8
        src2, applied = apply_rna(src, patch, stem)
        for a in applied:
            it.note(1, f"rna edit applied: {a}")
        src = src2
    stmts, notes, _ = parse(src)
    for nt in notes:
        # Z-CAPWINDOW (L-053): raw append — mirror of tools.rs
        # `interp.notes.push(n.clone())`: parse notes bypass the eval-note
        # cap (which counts the combined list from the first eval note).
        it.notes.append(nt)
    it.ires = [s[1] for s in stmts if s[0] == "ires"]
    # capability grants from .cell allow.* keys, only an EXPLICITLY passed
    # --cell may grant; auto-detected operon.cell keys are ignored with a note
    cell_explicit = cell is not None and isinstance(cell, dict)
    for k, v in list(it.cell.items()):
        if k.startswith("allow."):
            rest = k[len("allow."):]
            if rest == "exit":
                # sec-r2 (audit C-11): exit is a BOOLEAN capability
                # (rust tools.rs: exit_allowed = (v == "true")), not a
                # comma-separated grant list like the other six.
                if not cell_explicit:
                    it.note(1, f"cell key '{k}={v}' ignored: auto-detected operon.cell cannot grant capabilities (pass --cell explicitly)")
                    continue
                it.caps["exit"] = v == "true"
                continue
            if rest in ("read", "write", "run", "net", "env", "py"):
                if not cell_explicit:
                    it.note(1, f"cell key '{k}={v}' ignored: auto-detected operon.cell cannot grant capabilities (pass --cell explicitly)")
                    continue
                # cell values may carry a comma-separated grant list (parity
                # with the Rust runner's cell parsing)
                for g in v.split(","):
                    g = g.strip()
                    if g:
                        it.caps[rest].append(g)
    if it.cell.get("entry"):
        it.cell_entry = it.cell["entry"]
    if it.cell.get("methylate.quiet") == "true":
        it.methyl_quiet = True
    # .cell methylate.threshold (T2b graded silencing gate; default 3)
    _mthr = it.cell.get("methylate.threshold")
    if _mthr is not None:
        try:
            it.methyl_threshold = int(str(_mthr).strip())
        except ValueError:
            it.note(4, f"cell key 'methylate.threshold = {_mthr}' ignored: needs a non-negative integer")
    # reg-bio (F-6): enhancer dose (default 0.25)
    _ed = it.cell.get("enhance.delta")
    if _ed is not None:
        try:
            _f = float(str(_ed).strip())
            if 0.0 <= _f <= 1.0:
                it.enhance_delta = _f
            else:
                it.note(4, f"cell key 'enhance.delta = {_ed}' ignored: needs a number in 0..=1")
        except ValueError:
            it.note(4, f"cell key 'enhance.delta = {_ed}' ignored: needs a number in 0..=1")
    # reg-bio (F-1): telegraph promoter layer (opt-in)
    if it.cell.get("expression.stochastic", "").strip() == "true":
        it.expr_stochastic = True
    for _ck, _attr in (("expression.kon", "expr_kon"), ("expression.koff", "expr_koff")):
        _cv = it.cell.get(_ck)
        if _cv is not None:
            try:
                _f = float(str(_cv).strip())
                if 0.0 <= _f <= 1.0:
                    setattr(it, _attr, _f)
                else:
                    it.note(4, f"cell key '{_ck} = {_cv}' ignored: needs a number in 0..=1")
            except ValueError:
                it.note(4, f"cell key '{_ck} = {_cv}' ignored: needs a number in 0..=1")
    _esd = it.cell.get("expression.seed")
    if _esd is not None:
        try:
            _s = int(str(_esd).strip())
            it.rng = 0x9E3779B97F4A7C15 if _s == 0 else (_s & M64)
        except ValueError:
            it.note(4, f"cell key 'expression.seed = {_esd}' ignored: needs an integer")
    # reg-bio (F-5): repressilator kinetics, plasmid engineering surface
    for _ck, _lo, _hi in (("repressi.alpha", None, None), ("repressi.gamma", None, None),
                          ("repressi.basal", None, None), ("repressi.noise", None, None)):
        _cv = it.cell.get(_ck)
        if _cv is None:
            continue
        try:
            _f = float(str(_cv).strip())
        except ValueError:
            it.note(4, f"cell key '{_ck} = {_cv}' ignored: needs a number")
            continue
        _key = _ck.split(".")[1]
        if _key == "alpha" and _f > 0.0:
            it.repressi_params["alpha"] = _f
        elif _key == "gamma" and _f >= 0.0:
            it.repressi_params["gamma"] = _f
        elif _key == "basal" and _f >= 0.0:
            it.repressi_params["basal"] = _f
        elif _key == "noise" and 0.0 <= _f <= 1.0:
            it.repressi_params["noise"] = _f
        elif _key == "alpha":
            it.note(4, f"cell key '{_ck} = {_cv}' ignored: needs a number > 0")
        elif _key == "gamma" or _key == "basal":
            it.note(4, f"cell key '{_ck} = {_cv}' ignored: needs a number >= 0")
        elif _key == "noise":
            it.note(4, f"cell key '{_ck} = {_cv}' ignored: needs a number in 0..=1")
    _rh = it.cell.get("repressi.hill")
    if _rh is not None:
        try:
            _n = int(str(_rh).strip())
            if 1 <= _n <= 8:
                it.repressi_params["hill"] = _n
            else:
                it.note(4, f"cell key 'repressi.hill = {_rh}' ignored: needs an integer 1..=8")
        except ValueError:
            it.note(4, f"cell key 'repressi.hill = {_rh}' ignored: needs an integer 1..=8")
    _rsd = it.cell.get("repressi.seed")
    if _rsd is not None:
        try:
            _s = int(str(_rsd).strip())
            it.repressi_params["seed"] = 0x9E3779B97F4A7C15 if _s == 0 else (_s & M64)
        except ValueError:
            it.note(4, f"cell key 'repressi.seed = {_rsd}' ignored: needs an integer")
    for st in stmts:
        try:
            with contextlib.suppress(Return, BreakLoop, ContinueLoop):
                it.exec_stmt(it.globals, st)
        except Stress as e:
            # W06 (D-014) mirror: top-level propagation passes through.
            if e.prop is not None:
                it.note(4, f"propagation reached top level: {v_repr(e.prop)} passes through")
            else:
                it.note(4, f"stress contained: [{e.kind}] {e.message}")
    proofs, frames, exports, tad_exports, tad_members, ires = collect_structure(stmts)
    return it, stmts, proofs, frames

def resolve_entry(it, stmts, entry=None, use_ires=False):
    if entry:
        return entry
    if it.cell_entry:
        return it.cell_entry
    if use_ires and it.ires:
        return it.ires[0]
    if any(s[0] == "gene" and s[1].name == "main" for s in stmts):
        return "main"
    if it.ires:
        return it.ires[0]
    return None

def run(path, cell=None, variant=None, rna=None, entry=None, frame=None, args=None, caps=None):
    it, stmts, proofs, frames = load_file(path, cell, variant, rna, args, caps)
    if frame:
        for nm, body in frames:
            if nm == frame:
                it.exec_block(it.new_scope(it.globals), body)
    else:
        e = resolve_entry(it, stmts, entry)
        if e:
            argv = list(args or [])
            g = it.globals.get(e)
            # the entry frame is an AUTO-invocation: no call-site line (the
            # engines render a bare `at main` for the entry frame)
            it.cur_line = 0
            # Z-132 (#132 class D) NOTE: the entry-call stress does NOT get
            # contained here — the engines escape it to the CLI boundary,
            # which renders the W101 fatal block and exits 1 (the run cmd's
            # handler below mirrors that render). Containing it here would
            # make every gene-body failure look like a top-level note.
            if isinstance(g, Gene) and g.params:
                try:
                    it.call_gene(g, [argv])
                except Stress as err:
                    # the buffered notes ride to the CLI handler (the engines
                    # flush them AFTER the fatal render — order pinned)
                    err.oracle_interp = it
                    raise
            elif isinstance(g, Gene):
                try:
                    it.call_gene(g, [])
                except Stress as err:
                    err.oracle_interp = it
                    raise
            else:
                it.call_named(it.globals, e, [argv])
    return it
