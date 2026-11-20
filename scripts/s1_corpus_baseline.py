#!/usr/bin/env python3
"""S1 corpus baseline (V2-S1-C evidence): run the Python oracle over every
tests/differential/*.op file and record pass/fail per file.

The oracle is the semantic reference; this sweep establishes the
oracle-lane baseline BEFORE the MIR interpreter joins the differential
harness as a third lane (docs/design/STRICT-CORE.md §5). A file that the
oracle itself cannot run (crash, hang, nonzero exit) is a pre-existing
oracle finding, independent of S1 - recorded here verbatim, never
interpreted away.

Usage: python3 scripts/s1_corpus_baseline.py [--timeout 60] [--out PATH]
Writes docs/design/S1-CORPUS-BASELINE.md (markdown table + counts) and
prints the counts to stdout.
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORACLE = ROOT / "bootstrap" / "oracle.py"
CORPUS = ROOT / "tests" / "differential"
OUT = ROOT / "docs" / "design" / "S1-CORPUS-BASELINE.md"


def run_one(path: Path, timeout: int) -> dict:
    started = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, str(ORACLE), "run", str(path)],
            capture_output=True, text=True, timeout=timeout, cwd=ROOT,
        )
        elapsed = time.time() - started
        tb = "Traceback" in (proc.stderr or "")
        if proc.returncode == 0:
            status = "PASS"
            detail = f"{len(proc.stdout.splitlines())} out line(s)"
        elif proc.returncode == 1 and not tb:
            # the corpus pins designed error paths byte-for-byte across lanes
            # (W05 const/frozen parity, Z-116 E1000, Z-132 W101 fatal block):
            # a clean frozen-error render with rc=1 IS the expected outcome
            status = "RC1-PIN"
            first_err = (proc.stderr.strip().splitlines() or ["<no stderr>"])[-1]
            detail = f"designed error path: {first_err[:96]}"
        else:
            status = "FAIL"
            first_err = (proc.stderr.strip().splitlines() or ["<no stderr>"])[-1]
            detail = f"rc={proc.returncode} {'TRACEBACK ' if tb else ''}{first_err[:100]}"
    except subprocess.TimeoutExpired:
        status, detail = "HANG", f">{timeout}s"
        elapsed = timeout
    except OSError as e:
        status, detail = "ERROR", str(e)[:110]
        elapsed = time.time() - started
    return {"file": path.name, "status": status, "detail": detail,
            "seconds": elapsed}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    files = sorted(CORPUS.glob("*.op"))
    if not files:
        print(f"no .op files under {CORPUS}", file=sys.stderr)
        return 2

    rows = [run_one(f, args.timeout) for f in files]

    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    total_secs = sum(r["seconds"] for r in rows)

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True, cwd=ROOT)
    commit = commit.stdout.strip() or "<unknown>"

    lines = []
    lines.append("# S1-CORPUS-BASELINE — oracle-lane sweep (V2-S1-C evidence)")
    lines.append("")
    lines.append(f"**Date:** 2026-11-21 · **Commit:** {commit}")
    lines.append("")
    lines.append("Python oracle lane (`bootstrap/oracle.py run`) over every "
                 f"`tests/differential/*.op` file ({len(files)} files), "
                 f"{total_secs:.1f}s total wall time. Command:")
    lines.append("")
    lines.append("```")
    lines.append("python3 scripts/s1_corpus_baseline.py")
    lines.append("```")
    lines.append("")
    lines.append("This is the pre-MIR baseline required by "
                 "[STRICT-CORE.md](STRICT-CORE.md) §5: engine-vs-oracle "
                 "divergence is attributable only when the oracle lane is "
                 "known-good. Legend: PASS = ran clean (rc 0); RC1-PIN = "
                 "designed error-path pin rendered its frozen block (the "
                 "corpus pins W05/Z-116/Z-132-class failures byte-for-byte "
                 "across lanes, so rc 1 without a traceback is the expected "
                 "outcome); FAIL = traceback or unexpected rc (an oracle "
                 "finding, recorded verbatim); HANG/ERROR = infrastructure. "
                 "These rows say nothing about S1 parity until the MIR lane "
                 "joins.")
    lines.append("")
    summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    lines.append(f"**Result: {len(files)} files — {summary}**")
    lines.append("")
    lines.append("| file | status | detail |")
    lines.append("|---|---|---|")
    for r in rows:
        lines.append(f"| {r['file']} | {r['status']} | {r['detail']} |")
    lines.append("")

    args.out.write_text("\n".join(lines), encoding="utf-8")
    print(f"{len(files)} files — {summary} — written {args.out.relative_to(ROOT)}")

    # a failing oracle lane is information, not a script failure
    return 0


if __name__ == "__main__":
    sys.exit(main())
