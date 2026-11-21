"""operon oracle: shim (split of bootstrap/oracle.py)."""

import sys
import os
from oracle_lib.bio import parse_cell
from oracle_lib.fmt import v_repr
from oracle_lib.loader import load_file, run
from oracle_lib.parser import parse
from oracle_lib.values import BreakLoop, ContinueLoop, Return, Stress, note_code


#!/usr/bin/env python3
"""oracle.py, Operon reference implementation (bootstrap layer).

Role in the stack: the semantic oracle used by the differential test harness
to cross-check the Rust core, plus the packaging path. It implements the same
frozen SPEC.md semantics as the Rust core: Total Grammar 4-rung ladder,
gene-expression regulation layer, and the same display rules.

Deliberately sequential: spawn() runs tasks inline (deterministic), which is
equivalent for the differential corpus.
"""

def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(2)
    cmd = argv[0]
    rest = argv[1:]
    opts = {"cell": None, "variant": None, "rna": None, "entry": None, "frame": None, "args": []}
    pos = []
    i = 0
    while i < len(rest):
        a = rest[i]
        if a == "--cell":
            i += 1; opts["cell"] = rest[i]
        elif a == "--variant":
            i += 1; opts["variant"] = rest[i]
        elif a == "--rna":
            i += 1; opts["rna"] = rest[i]
        elif a == "--entry":
            i += 1; opts["entry"] = rest[i]
        elif a == "--frame":
            i += 1; opts["frame"] = rest[i]
        elif a == "--json":
            opts["json"] = True
        elif a in ("--allow-read", "--allow-write", "--allow-run", "--allow-net", "--allow-env", "--allow-py"):
            i += 1
            cap = a.replace("--allow-", "")
            it_caps = opts.setdefault("caps", {"enabled": True, "read": [], "write": [], "run": [], "net": [], "env": [], "py": [], "exit": False})
            it_caps[cap].append(rest[i])
        elif a == "--allow-exit":
            # sec-r2 (audit C-11): exit() is a capability, default-deny
            # (S3: the coverage audit caught the missing flag mirror)
            it_caps = opts.setdefault("caps", {"enabled": True, "read": [], "write": [], "run": [], "net": [], "env": [], "py": [], "exit": False})
            it_caps["exit"] = True
        elif a == "--allow-all":
            opts["caps"] = {"enabled": False, "read": [], "write": [], "run": [], "net": [], "env": [], "py": [], "exit": False}
        else:
            pos.append(a)
        i += 1
    # loop-10: load the --cell FILE into the dict the interpreter expects
    # (the flag previously leaked the path string into Interp(cell=...),
    # AttributeError on .items(); the Rust CLI parses the file, so did we)
    cell_dict = None
    if opts["cell"]:
        with open(opts["cell"], encoding="utf-8", errors="replace") as _cf:  # W59: explicit UTF-8
            cell_dict = parse_cell(_cf.read())
    if cmd == "version":
        print("Operon 2.0.0 (python-oracle)")
    elif cmd == "run":
        # Z-132 (#132 class D): a stress that escapes the entry call is the
        # engines' W101 fatal path — the compact render on stderr (header +
        # W007 chain, call-site lines when known) and exit 1. A Python
        # traceback here turned every would-be honest differential into an
        # anonymous crash wall (both sides non-zero, class rides through).
        try:
            it = run(pos[0], cell_dict, opts["variant"], opts["rna"], opts["entry"], opts["frame"], pos[1:], caps=opts.get("caps"))
        except Stress as err:
            code = {"missing": "E1002", "unfolded": "E1003", "unwrap": "E1004",
                    "overflow": "E1020", "burned": "E1021"}.get(err.kind, "E1000")
            block = f"error[{code}]: {err.message}\n"
            if err.chain:
                block += "\n"
                for gname, gline in err.chain:
                    if gline:
                        block += f"  at {gname} ({pos[0]}:{gline})\n"
                    else:
                        block += f"  at {gname}\n"
            print(block, file=sys.stderr, end="")
            _it = getattr(err, "oracle_interp", None)
            if _it is not None:
                for nt in _it.notes:
                    _tag = {1: "info", 2: "synonym", 3: "wobble"}.get(nt.rung, "fallback")
                    _code = note_code(nt.message)
                    _tag_s = f"{_tag} {_code}" if _code else _tag
                    if getattr(nt, "line", 0) > 0:
                        print(f"[{_tag_s}] {pos[0]}:{nt.line}: {nt.message}", file=sys.stderr)
                    else:
                        print(f"[{_tag_s}] {nt.message}", file=sys.stderr)
            sys.exit(1)
        for nt in it.notes:
            tag = {1: "info", 2: "synonym", 3: "wobble"}.get(nt.rung, "fallback")
            # W101 slice 7 mirror: derived E2xxx code rides the tag when the
            # message maps to a catalog family, exactly like flush_notes.
            code = note_code(nt.message)
            tag_s = f"{tag} {code}" if code else tag
            # A13/dx-r2 mirror: notes carry real locations (compat matrix
            # fix) — `[tag] file:line: msg` exactly like tools::flush_notes
            if getattr(nt, "line", 0) > 0:
                print(f"[{tag_s}] {pos[0]}:{nt.line}: {nt.message}", file=sys.stderr)
            else:
                print(f"[{tag_s}] {nt.message}", file=sys.stderr)
    elif cmd == "test":
        paths = pos or ["tests"]
        files = []
        for p in paths:
            if os.path.isdir(p):
                for root, _, fns in os.walk(p):
                    # reg-r4: adversarial red-team payloads are containment
                    # expectations, not proof frames, the Rust runner skips
                    # this directory too (parity; the walk used to crash on
                    # one of the payloads)
                    if "redteam" in root.replace(os.sep, "/"):
                        continue
                    # substrate-r1: capability-granted proofs run only under
                    # an explicit operator cell (Rust runner skips them too)
                    if "granted" in root.replace(os.sep, "/"):
                        continue
                    # W18: cancellation timing proofs need real OS threads;
                    # the sequential engine cannot observe mid-flight
                    # cancellation, so this lane is Rust-only (the Rust
                    # walker skips it too)
                    if "timing" in root.replace(os.sep, "/"):
                        continue
                    # W08r: the async corpus is cell-gated (io.pool =
                    # "fiber"); the thread lane's wall-clock fuel charging
                    # is runner-speed-dependent (the Rust walker skips it
                    # too)
                    if "async" in root.replace(os.sep, "/"):
                        continue
                    for fn in sorted(fns):
                        if fn.endswith(".op"):
                            files.append(os.path.join(root, fn))
            else:
                files.append(p)
        files.sort()
        files_t, proofs, passed, failed, failures = 0, 0, 0, 0, []
        for f in files:
            # reg-r4: a file that fails to LOAD is a suite failure, not a
            # crash of the runner (the Rust runner records it and continues)
            try:
                it, stmts, proofs_l, frames = load_file(f, cell_dict, opts["variant"], opts["rna"])
            except RecursionError:
                failed += 1
                failures.append(f"{f}: load error: recursion limit (parser depth)")
                continue
            except Exception as ex:
                failed += 1
                failures.append(f"{f}: load error: {type(ex).__name__}: {ex}")
                continue
            files_t += 1
            proofs += len(proofs_l)
            it.proof_mode = True
            for pi, pf in enumerate(proofs_l):
                # S4-6b (§12): the proof-integrity rules, mirrored from the
                # canonical rust runner (tools.rs test cmd): a proof that
                # completes with ZERO executed asserts is VACUOUS (fails,
                # never passes silently), and a frame-level return/break/
                # continue abandons the frame (fails, "exited early") — a
                # loop-INTERNAL break is normal completion (the loop
                # consumes the flow; BreakLoop never reaches here then).
                asserts_before = it.asserts_run
                try:
                    it.exec_block(it.new_scope(it.globals), pf)
                except (Return, BreakLoop, ContinueLoop):
                    failed += 1
                    failures.append(f"{f} proof #{pi+1}: exited early (return/break inside proof)")
                    continue
                except Stress as st:
                    failed += 1
                    # W06 (D-014) mirror: propagation abandoning a proof frame
                    # is a failure (the frame did not complete).
                    if st.prop is not None:
                        failures.append(f"{f}: propagation left the proof frame ({v_repr(st.prop)})")
                    else:
                        failures.append(f"{f}: [{st.kind}] {st.message}")
                except Exception as ex:
                    failed += 1
                    failures.append(f"{f}: [oracle-error] {type(ex).__name__}: {ex}")
                else:
                    if it.asserts_run == asserts_before:
                        failed += 1
                        failures.append(f"{f} proof #{pi+1}: no assertion exercised (vacuous proof)")
                    else:
                        passed += 1
        print(f"operon test, {files_t} file(s), {proofs} proof(s): {passed} passed, {failed} failed")
        for f in failures:
            print(f"  FAIL {f}", file=sys.stderr)
        if failed:
            sys.exit(1)
    elif cmd == "check":
        src = open(pos[0], encoding="utf-8", errors="replace").read()  # W59: explicit UTF-8
        stmts, notes, _ = parse(src)
        score = 100 - sum(1 if n.rung == 2 else (2 if n.rung == 3 else (3 if n.rung == 4 else 0)) for n in notes)
        letter = "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else "D" if score >= 60 else "F"
        print(f"operon check: {pos[0]}, score {max(score, 50)}/100 (grade {letter})")
    else:
        print("oracle supports: run | test | check | version", file=sys.stderr)
        sys.exit(2)

if __name__ == "__main__":
    # deep recursion support: run on a worker thread with a large stack and a
    # raised recursion limit, mirroring the Rust core's 512 MiB worker + 10k
    # Operon-frame depth limit. Runaway recursion surfaces as RecursionError,
    # never a native crash.
    #
    # W59 (Windows truthing), two fixes to the runner itself:
    #
    # 1. Honest exit codes. The worker-thread form used to swallow every
    #    failure: an exception inside main() printed a traceback and the
    #    process still exited 0, and main()'s own sys.exit() only ended the
    #    thread. A dead oracle therefore looked SUCCESSFUL to any caller
    #    that checks exit codes, the differential harness compares them.
    #    The worker now records the outcome and the main thread re-raises it
    #    as the process exit code.
    #
    # 2. Portable stack size. 1 << 29 sits exactly at Windows' 512 MiB
    #    threading.stack_size() ceiling; treat the request as best-effort
    #    with a fallback ladder instead of a hard startup dependency.
    sys.setrecursionlimit(150_000)
    import threading as _th

    for _sz in (1 << 29, 1 << 28, 1 << 26):
        try:
            _th.stack_size(_sz)
            break
        except (ValueError, RuntimeError, OverflowError):
            continue

    _rc = {"code": 0}

    def _worker():
        try:
            main()
        except SystemExit as _e:
            _rc["code"] = _e.code if isinstance(_e.code, int) else (0 if _e.code is None else 1)
        except BaseException:
            import traceback
            traceback.print_exc()
            _rc["code"] = 1

    _t = _th.Thread(target=_worker, name="oracle-worker")
    _t.start()
    _t.join()
    if _rc["code"]:
        sys.exit(_rc["code"])
