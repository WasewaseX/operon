"""operon oracle: fmt (split of bootstrap/oracle.py)."""

from .mapops import _map_items, _map_len



# display rules (must match Rust value.rs)
def fmt_float(f):
    if f != f:
        return "nan"
    if f == float("inf"):
        return "inf"
    if f == float("-inf"):
        return "-inf"
    # Python repr IS the canonical float format (shortest round-trip,
    # scientific when exp < -4 or >= 16, ".0" on integral positional values)
    return repr(f)

def escape_str(s):
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")

def escape_bytes(b):
    # W029 mirror of the Rust escape_bytes, printable ASCII raw, the C
    # escape set short-form, everything else \xNN two-hex-digit lowercase.
    out = ""
    for byte in b:
        if byte == 0x0a: out += "\\n"
        elif byte == 0x09: out += "\\t"
        elif byte == 0x0d: out += "\\r"
        elif byte == 0x22: out += '\\"'
        elif byte == 0x5c: out += "\\\\"
        elif 0x20 <= byte <= 0x7e: out += chr(byte)
        else: out += "\\x%02x" % byte
    return out

def is_identlike(s):
    # Z-125 (item 6): ASCII-only, mirroring the Rust lexer's charset
    # (SPEC §Identifiers) — Unicode-permissive display conflation removed.
    return bool(s) and (s[0].isascii() and s[0].isalpha() or s[0] == "_") and all(c.isascii() and (c.isalnum() or c == "_") for c in s)

def v_repr(v, _seen=None, _depth=0):
    # reg-r4 (re-audit B-3): cycle-safe, a container containing itself
    # renders the [...] / {...} marker at depth > 256 or on a re-entry
    # (mirror of the Rust core; the old version recursed forever)
    from .values import Channel, Gene, ObjInst, SeqObj, Variant, WeakRef
    if _seen is None:
        _seen = set()
    if _depth > 256:
        return "[...]"
    if v is None: return "null"
    if v is True: return "true"
    if v is False: return "false"
    if isinstance(v, int): return str(v)
    if isinstance(v, float): return fmt_float(v)
    if isinstance(v, str): return f'"{escape_str(v)}"'
    if isinstance(v, bytes): return f'b"{escape_bytes(v)}"'
    if isinstance(v, list):
        marker = id(v)
        if marker in _seen:
            return "[...]"
        _seen.add(marker)
        out = "[" + ", ".join(v_repr(x, _seen, _depth + 1) for x in v) + "]"
        _seen.discard(marker)
        return out
    if isinstance(v, dict):
        marker = id(v)
        if marker in _seen:
            return "{...}"
        _seen.add(marker)
        # Z-MAPORDER: _map_items is the pure insertion sequence (head+tail);
        # the old v.items() walk dropped side entries from repr entirely
        out = "{" + ", ".join(
            (k if isinstance(k, str) and is_identlike(k) else v_repr(k, _seen, _depth + 1))
            + ": " + v_repr(val, _seen, _depth + 1)
            for k, val in _map_items(v)) + "}"
        _seen.discard(marker)
        return out
    if isinstance(v, Gene):
        return f"<gene {v.name}>" if v.name else "<gene lambda>"
    # W06 mirror: variant repr mirrors mainstream constructor syntax; the
    # payload renders through v_repr so depth/cycle caps apply.
    if isinstance(v, Variant):
        if v.tag == "None":
            return "None"
        # W06 parity fix: a null payload is a REAL payload, ok(null) renders
        # Ok(null) like the Rust core (Some(Null)); the old payload-is-None
        # guard rendered the bare tag and hid the value
        return f"{v.tag}({v_repr(v.payload, _seen, _depth + 1)})"
    if isinstance(v, SeqObj):
        return f"<sequence {v.gene.name}>" if v.gene.name else "<sequence lambda>"
    if isinstance(v, ObjInst):
        return f"<phenotype {v.defn.name}>"
    # W015 mirror: address-free anonymous repr (see the Rust Channel arm)
    if isinstance(v, Channel):
        return "<channel>"
    # W013 mirror: address-free for the same reason; the target's identity
    # is observable only through strengthen(), never through repr.
    if isinstance(v, WeakRef):
        return "<weak>"
    return "<?>" 

def io_err(e):
    """Mirror the rust io::Error Display: '<strerror> (os error <N>)'.

    python's OSError str is '[Errno N] strerror: filename' — different
    bytes from the rust surface. The S3 granted lane (file_bytes_gaps)
    prints these messages, and the legacy file family's missing text was
    never corpus-covered before, so the drift was invisible (the try_
    twins mask it behind fixed payloads; the legacy arms embed the raw
    io::Error). The path itself is NOT part of io::Error Display — the
    rust arms format it separately before {e}."""
    strerror = e.strerror if e.strerror is not None else str(e)
    errno = e.errno if e.errno is not None else 0
    return f"{strerror} (os error {errno})"


def v_display(v):
    if isinstance(v, str):
        return v
    return v_repr(v)

def truthy(v):
    from .values import Variant
    if v is None or v is False: return False
    if v is True: return True
    if isinstance(v, (int, float)): return v != 0
    if isinstance(v, str): return len(v) > 0
    if isinstance(v, bytes): return len(v) > 0
    if isinstance(v, list): return len(v) > 0
    if isinstance(v, dict): return _map_len(v) > 0
    # W06 mirror: a carried success is truthy; a carried failure is falsy
    if isinstance(v, Variant): return v.tag in ("Some", "Ok")
    return True
