"""operon oracle: lexer (split of bootstrap/oracle.py)."""

from .values import Note



# ----------------------------------------------------------------------------
# lexer

SYMBOLS = ["**=", "<<=", ">>=", "+=", "-=", "*=", "/=", "%=", "==", "!=", "<=", ">=", "&&", "||",
           "//", "->", "=>", "**", "<<", ">>", "??", "?.", "?!", "&", "|", "^", "~", "?", "{", "}", "(", ")", "[", "]", ",", ":", "+", "-",
           "*", "/", "%", "=", "<", ">", "!", ".", ";"]

def lex(src):
    toks, notes = [], []
    i, line, n = 0, 1, len(src)
    while i < n:
        c = src[i]
        if c in " \t\r":
            i += 1; continue
        if c == "\n":
            if not toks or toks[-1][0] != "NL":
                toks.append(("NL", None, line))
            line += 1; i += 1; continue
        if c == "#":
            while i < n and src[i] != "\n":
                i += 1
            continue
        # W030 mirror: raw strings r"...", no escapes, no interpolation
        if c == "r" and i + 1 < n and src[i+1] == '"':
            i += 2
            raw, closed = "", False
            while i < n:
                if src[i] == '"':
                    i += 1; closed = True; break
                if src[i] == "\n":
                    line += 1
                raw += src[i]; i += 1
            if not closed:
                notes.append(Note(4, "unclosed raw string consumed to end of input", line))
            toks.append(("STR", raw, line))
            continue
        # W029 mirror: bytes literals b"..." / b'...', same escape set as the
        # Rust lexer (\n \t \r \\ \" \' \0 \xNN; unknown escapes verbatim; no
        # interpolation); non-ASCII encodes as UTF-8 with a note.
        if (c == "b" or c == "B") and i + 1 < n and src[i+1] in ('"', "'"):
            quote = src[i+1]
            if quote == "'":
                notes.append(Note(4, "single-quoted bytes literal repaired to double quotes"))
            i += 2
            out = bytearray()
            closed = False
            while i < n:
                if src[i] == quote:
                    i += 1; closed = True; break
                if src[i] == "\\" and i + 1 < n:
                    e = src[i + 1]
                    if e == "n": out.append(10)
                    elif e == "t": out.append(9)
                    elif e == "r": out.append(13)
                    elif e == "0": out.append(0)
                    elif e == "\\": out.append(92)
                    elif e == '"': out.append(34)
                    elif e == "'": out.append(39)
                    elif e == "x":
                        if i + 3 < n and all(ch in "0123456789abcdefABCDEF" for ch in src[i+2:i+4]):
                            out.append(int(src[i+2:i+4], 16))
                            i += 4; continue
                        notes.append(Note(4, "malformed \\x escape in bytes literal kept verbatim"))
                        out.append(92); out.append(120)
                    else:
                        out.append(92); out.extend(e.encode("utf-8"))
                    i += 2; continue
                if src[i] == "\n":
                    line += 1
                if ord(src[i]) > 127:
                    notes.append(Note(4, "non-ASCII char in bytes literal encoded as UTF-8"))
                    out.extend(src[i].encode("utf-8"))
                else:
                    out.append(ord(src[i]))
                i += 1
            if not closed:
                notes.append(Note(4, "unclosed bytes literal consumed to end of input"))
            toks.append(("BYTES", bytes(out), line))
            continue
        # W030 mirror: multiline triple-quoted strings """...""", escapes and
        # interpolation processed, content verbatim
        if c == '"' and i + 2 < n and src[i+1] == '"' and src[i+2] == '"':
            i += 3
            raw, closed, interp, depth = "", False, False, 0
            while i < n:
                if src[i] == '"' and i + 2 < n and src[i+1] == '"' and src[i+2] == '"':
                    i += 3; closed = True; break
                if src[i] == "\\" and i + 1 < n:
                    e = src[i + 1]
                    raw += {"n": "\n", "t": "\t", "\\": "\\", '"': '"', "{": "{", "}": "}"}.get(e, "\\" + e)
                    i += 2; continue
                if src[i] == "\n":
                    line += 1
                if src[i] == "{":
                    depth += 1; interp = True
                if src[i] == "}" and depth > 0:
                    depth -= 1
                raw += src[i]; i += 1
            if not closed:
                notes.append(Note(4, "unclosed multiline string consumed to end of input", line))
            toks.append(("INTERP" if interp else "STR", raw, line))
            continue
        if c == '"':
            raw, i2, closed, interp = "", i + 1, False, False
            depth = 0
            while i2 < n:
                ch = src[i2]
                if ch == "\\" and i2 + 1 < n:
                    e = src[i2 + 1]
                    raw += {"n": "\n", "t": "\t", "\\": "\\", '"': '"', "{": "{", "}": "}"}.get(e, "\\" + e)
                    i2 += 2; continue
                if depth == 0 and ch == '"':
                    closed = True; i2 += 1; break
                if ch == "\n":
                    line += 1
                if ch == "{":
                    depth += 1; interp = True
                if ch == "}" and depth > 0:
                    depth -= 1
                raw += ch; i2 += 1
            if not closed:
                notes.append(Note(4, "unclosed string consumed to end of file", line))
            toks.append(("INTERP" if interp else "STR", raw, line))
            i = i2; continue
        if c == "'":
            notes.append(Note(4, "single-quoted string repaired to double quotes", line))
            raw, i2, closed = "", i + 1, False
            while i2 < n:
                ch = src[i2]
                if ch == "\\" and i2 + 1 < n:
                    e = src[i2 + 1]
                    raw += {"n": "\n", "t": "\t", '"': '"'}.get(e, e)
                    i2 += 2; continue
                if ch == "'":
                    closed = True; i2 += 1; break
                if ch == "\n":
                    line += 1
                raw += ch; i2 += 1
            if not closed:
                notes.append(Note(4, "unclosed string consumed to end of file", line))
            toks.append(("STR", raw, line))
            i = i2; continue
        if c == "@":
            j = i + 1
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            if j > i + 1:
                toks.append(("MARK", src[i + 1:j], line))
            else:
                notes.append(Note(4, "stray '@' skipped", line))
            i = j; continue
        if c.isdigit():
            # W031 mirror: radix prefixes 0x/0b/0o (case-insensitive) with `_`
            # separators; prefix with no valid digit falls through to decimal
            if c == "0" and i + 1 < n and src[i+1] in "xXbBoO":
                radix = {"x": 16, "X": 16, "b": 2, "B": 2, "o": 8, "O": 8}[src[i+1]]
                vset = "0123456789abcdefABCDEF" if radix == 16 else ("01" if radix == 2 else "01234567")
                if i + 2 < n and (src[i+2] in vset or src[i+2] == "_"):
                    j = i + 2
                    while j < n and (src[j] in vset or src[j] == "_"):
                        j += 1
                    raw = src[i:j]
                    digits = raw[2:].replace("_", "")
                    # Z-132 (#132 class C): a radix lexeme of only `_`
                    # separators (0x_, 0b_, 0o_) has NO digits — the engine's
                    # documented repair path treats it as out-of-range: value
                    # 0 + the E2008 note, never a ValueError crash.
                    if digits:
                        val = int(digits, radix)
                        toks.append(("INT", val, line))
                        # i64 parity: out-of-range treated as 0 with the same note
                        if not (-2**63 <= val <= 2**63 - 1):
                            notes.append(Note(4, f"integer '{raw}' out of range treated as 0", line))
                            toks[-1] = ("INT", 0, line)
                    else:
                        notes.append(Note(4, f"integer '{raw}' out of range treated as 0", line))
                        toks.append(("INT", 0, line))
                    i = j; continue
            j = i
            isf = False
            while j < n and (src[j].isdigit() or src[j] == "." or src[j] == "_"):
                if src[j] == ".":
                    if j + 1 >= n or not src[j + 1].isdigit():
                        break
                    isf = True
                j += 1
            if j < n and src[j] in "eE":
                k = j + 1
                if k < n and src[k] in "+-":
                    k += 1
                if k < n and src[k].isdigit():
                    isf = True
                    j = k
                    while j < n and src[j].isdigit():
                        j += 1
            text = src[i:j]
            # W031 mirror: `_` separators stripped before parsing
            cleaned = text.replace("_", "")
            try:
                toks.append(("FLOAT", float(cleaned), line) if isf else (("INT", int(cleaned), line)))
            except ValueError:
                notes.append(Note(4, f"malformed number '{text}' treated as 0", line))
                toks.append(("INT", 0, line))
            else:
                # parity with the Rust lexer: an integer literal beyond i64
                # is out of range and treated as 0 with the same note (the
                # Rust core parses i64; a Python bignum would otherwise see
                # a value the compiled engine never did)
                if not isf and not (-2**63 <= int(cleaned) <= 2**63 - 1):
                    notes.append(Note(4, f"integer '{text}' out of range treated as 0", line))
                    toks[-1] = ("INT", 0, line)
            i = j; continue
        if c.isascii() and (c.isalpha() or c == "_"):
            j = i
            # Z-125 (item 6): ASCII-only identifiers, mirroring the Rust
            # lexer's is_ascii_alphanumeric scan (SPEC §Identifiers) — the
            # old Unicode-permissive scan made `café` one ident here and
            # two tokens in the core, breaking byte-identical parity.
            while j < n and src[j].isascii() and (src[j].isalnum() or src[j] == "_"):
                j += 1
            toks.append(("IDENT", src[i:j], line))
            i = j; continue
        if c == "?" and i + 2 < n and src[i+1] == "." and src[i+2].isdigit():
            # L1a parity guard: '?.' followed by a digit lexes as '?' + number-dot
            toks.append(("SYM", "?", line))
            i += 1
            continue
        matched = False
        for sym in SYMBOLS:
            if src.startswith(sym, i):
                toks.append(("SYM", sym, line))
                i += len(sym)
                matched = True
                break
        if not matched:
            notes.append(Note(4, f"unexpected character '{c}' skipped", line))
            i += 1
    toks.append(("EOF", None, line))
    return toks, notes

# ----------------------------------------------------------------------------
# parser, Total Grammar ladder

KEYWORDS = set("""gene let if elif else while loop scope for in return break continue match case use
tad anchor export import enhance silence stress rescue raise fate state regulate activates
inhibits strength toggle repressilator period frame proof guard splice variant edit replace
ires as collect enter phenotype sequence yield new threshold from self operon""".split())

ARMS = set("""gene let if elif else while loop scope for return break continue match use tad anchor
enhance silence stress raise fate regulate toggle repressilator frame splice edit ires
phenotype sequence yield operon""".split())

SYNONYMS = {
    "fn": "gene", "func": "gene", "fun": "gene", "def": "gene", "sub": "gene",
    "lambda": "gene", "proc": "gene", "var": "let", "val": "let",
    "foreach": "for", "each": "for", "import": "use", "include": "use",
    "require": "use", "ret": "return", "stop": "break", "next": "continue",
    "skip": "continue", "elseif": "elif",
    "class": "phenotype", "struct": "phenotype", "record": "phenotype", "prototype": "phenotype",
    "type": "phenotype", "generator": "sequence", "gen": "sequence", "stream": "sequence", "iter": "sequence",
}
VALUE_SYNONYMS = {"yes": True, "on": True, "no": False, "off": False,
                  "nil": None, "nothing": None}
# W06 (D-014) mirror: 'none' RETIRED from VALUE_SYNONYMS, it is now the
# Option constructor none(); bare 'none' degrades to an unbound ident
# (phantom note), never a silent null. Matches src/parser.rs.
# W64: metadata-only deprecation mark, known so the wobble repair
# never mangles it; the payload parse is lenient, runtime never reads it
MARKS = {"acetylate", "methylate", "m6a", "copies", "riboswitch", "burst", "deprecated"}

def edit_distance(a, b):
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if la == 0: return lb
    if lb == 0: return la
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[lb]

def wobble_keyword(word):
    limit = 1 if len(word) <= 4 else 2
    best, bd = None, 99
    for k in KEYWORDS:
        d = edit_distance(word, k)
        if d <= limit and d < bd:
            best, bd = k, d
    return best
