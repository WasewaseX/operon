"""operon oracle: bio (split of bootstrap/oracle.py)."""

from .parser import parse



def collect_structure(stmts):
    proofs, frames, exports, tad_exports, tad_members, ires = [], [], [], [], [], []
    def walk(body):
        for s in body:
            if s[0] == "frame":
                if s[2]:
                    proofs.append(s[3])
                else:
                    frames.append((s[1], s[3]))
                walk(s[3])
            elif s[0] == "tad":
                members, exps = [], []
                for x in s[2]:
                    if x[0] == "anchor_export":
                        exps.extend(x[1])
                    if x[0] == "gene" and x[1].name:
                        members.append(x[1].name)
                    if x[0] == "let":
                        members.append(x[1])
                tad_exports.append((s[1], exps))
                tad_members.append((s[1], members))
                walk(s[2])
            elif s[0] == "anchor_export":
                exports.extend(s[1])
            elif s[0] == "ires":
                ires.append(s[1])
            elif s[0] == "gene":
                walk(s[1].body)
                if s[1].guard:
                    walk(s[1].guard[1])
            elif s[0] == "splice":
                for _, _vp, vb, _mk, _vl in s[2]:
                    walk(vb)
    walk(stmts)
    return proofs, frames, exports, tad_exports, tad_members, ires

def parse_cell(src):
    out = {}
    section = ""
    for line in src.splitlines():
        t = line.strip()
        if not t or t.startswith("#"):
            continue
        if t.startswith("[") and t.endswith("]"):
            section = t[1:-1].strip()
            continue
        if "=" in t:
            k, v = t.split("=", 1)
            kk = f"{section}.{k.strip()}" if section else k.strip()
            out[kk] = v.strip().strip('"')
    return out

def apply_rna(src, patch_src, stem):
    applied = []
    stmts, _, _ = parse(patch_src)
    text = src
    for s in stmts:
        if s[0] == "edit":
            target, reps = s[1], s[2]
            if target not in (stem, "anywhere"):
                start = text.find(f"gene {target}")
                if start >= 0:
                    end = text.find("\ngene ", start + 5)
                    end = end + 1 if end >= 0 else len(text)
                    seg = text[start:end]
                    seg2 = seg
                    for frm, to in reps:
                        if frm in seg2:
                            seg2 = seg2.replace(frm, to)
                            applied.append(f"{target}: '{frm}' -> '{to}'")
                    if seg2 != seg:
                        text = text[:start] + seg2 + text[end:]
            else:
                for frm, to in reps:
                    if frm in text:
                        text = text.replace(frm, to)
                        applied.append(f"{target}: '{frm}' -> '{to}'")
    return text, applied
