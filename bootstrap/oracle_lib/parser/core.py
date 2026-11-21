"""operon oracle: parser.core (split of bootstrap/oracle.py)."""

from ..lexer import SYNONYMS, wobble_keyword
from ..values import Note



class PCore:
    def __init__(self, toks, notes):
        self.toks, self.pos, self.notes = toks, 0, notes
        # Z-CAPWINDOW (L-053) mirror of parser.rs PARSE_NOTE_CAP: the 10k cap
        # counts PARSER-generated notes only (lexed.notes ride uncapped in
        # parser.rs — `let mut notes = lexed.notes` outside p.notes), so the
        # cap keys on the delta from the lexer-note base.
        self.parse_note_base = len(notes)
        # #111 mirror: ONE shared recursion budget across every recursive
        # descent site (paren/list/map/unary/postfix/pattern/block), matching
        # parser.rs `depth` op-for-op so truncation is byte-identical.
        self.depth = 0
        # W24: contextual `pub` marker names (top level only)
        self.pub_names = []
        # W01-s2 type aliases (mirror of parser.rs type_aliases +
        # type_param_stack): declared `type Name = ann` pairs in declaration
        # order + enclosing gene type parameters (shadow aliases).
        self.type_aliases = []
        self.type_param_stack = []

    def peek(self):
        return self.toks[self.pos]

    def next(self):
        t = self.toks[self.pos]
        if self.pos < len(self.toks) - 1:
            self.pos += 1
        return t

    def note(self, line, rung, msg):
        # Z-CAPWINDOW (L-053) mirror of parser.rs note(): sec-r4 (F-3) —
        # past the 10k cap, further parser notes are suppressed, one
        # boundary note at the exact cap (byte-identical render).
        PARSE_NOTE_CAP = 10_000
        generated = len(self.notes) - self.parse_note_base
        if generated >= PARSE_NOTE_CAP:
            if generated == PARSE_NOTE_CAP:
                self.notes.append(Note(4, "parse note cap (10000) reached, further notes suppressed", line))
            return
        self.notes.append(Note(rung, msg, line))

    def eat_nl(self):
        while self.peek()[0] in ("NL", "SYM") and (self.peek()[0] == "NL" or self.peek()[1] == ";"):
            self.next()

    def expect_kw(self, word):
        t = self.peek()
        if t[0] == "IDENT" and t[1] == word:
            self.next(); return True
        if t[0] == "IDENT":
            syn = SYNONYMS.get(t[1])
            if syn == word:
                self.note(t[2], 2, f"synonym '{t[1]}' repaired to '{word}'")
                self.next(); return True
            wk = wobble_keyword(t[1])
            if wk == word:
                self.note(t[2], 3, f"wobble: '{t[1]}' repaired to keyword '{word}'")
                self.next(); return True
        return False

    def at_ident(self, w):
        t = self.peek()
        return t[0] == "IDENT" and t[1] == w

    # program
    def program(self):
        out = []
        while True:
            self.eat_nl()
            if self.peek()[0] == "EOF":
                break
            if self.peek() == ("SYM", "}", self.peek()[2]):
                self.note(self.peek()[2], 4, "unmatched '}' skipped")
                self.next(); continue
            before = self.pos
            # W24 mirror: contextual `pub` marker, `pub gene` / `pub let` /
            # `pub const` / `pub phenotype` at TOP LEVEL records the name for
            # strict-mode export filtering. `pub` is NOT a keyword: an
            # ordinary identifier named `pub` is untouched (Total Grammar).
            t = self.peek()
            if t[0] == "IDENT" and t[1] == "pub":
                nt = self.toks[self.pos + 1] if self.pos + 1 < len(self.toks) else ("EOF", None, 0)
                if nt[0] == "IDENT" and nt[1] in ("gene", "let", "const", "phenotype"):
                    self.next()
                    s = self.stmt()
                    if s is not None:
                        name = None
                        if s[0] == "gene" and s[1].name:
                            name = s[1].name
                        elif s[0] in ("let", "const"):
                            name = s[1]
                        elif s[0] == "pheno":
                            name = s[1].name
                        if name:
                            self.pub_names.append(name)
                        out.append(s)
                    continue
            s = self.stmt()
            if s is not None:
                out.append(s)
            if self.pos == before:
                self.note(self.peek()[2], 4, f"token skipped")
                self.next()
        return out

    # statements
    def _trait_method_has_body(self):
        # W04: from the current 'gene' token, scan ahead past the matching
        # parameter parens; a '{' after the close paren means a default body.
        i = self.pos + 1
        n = len(self.toks)
        depth = 0
        seen_paren = False
        while i < n:
            t = self.toks[i]
            if t[0] == "SYM" and t[1] == "(":
                depth += 1
                seen_paren = True
            elif t[0] == "SYM" and t[1] == ")":
                depth -= 1
                if seen_paren and depth <= 0:
                    nx = self.toks[i + 1] if i + 1 < n else ("EOF", None, 0)
                    return nx[0] == "SYM" and nx[1] == "{"
            elif not seen_paren and t[0] == "SYM" and t[1] == "{":
                return True
            i += 1
        return False

    def _trait_params(self):
        # W04: consume `(a, b, ...)`, plain names (a signature, not a body).
        if not (self.peek()[0] == "SYM" and self.peek()[1] == "("):
            return []
        self.next()
        names = []
        while True:
            t = self.peek()
            if t[0] == "SYM" and t[1] == ")":
                self.next()
                break
            if t[0] == "IDENT":
                self.next()
                names.append(t[1])
                if t[1] == "Eq" or (self.peek()[0] == "SYM" and self.peek()[1] == "="):
                    self.next()
                    self.expr()
            elif t[0] == "EOF":
                break
            else:
                self.next()
        return names

    def skip_line(self):
        while self.peek()[0] not in ("NL", "EOF") and not (self.peek()[0] == "SYM" and self.peek()[1] == "}"):
            self.next()

    def end_stmt(self):
        if self.peek()[0] == "NL" or (self.peek()[0] == "SYM" and self.peek()[1] == ";"):
            self.next()

    def ident(self):
        t = self.peek()
        if t[0] == "IDENT":
            self.next()
            return t[1]
        self.note(t[2], 4, f"expected a name, found token; used '?'")
        return "?"

    def use_path(self):
        # segments joined by separators; boundary words ('as') never glue in
        # W25 mirror: `::` is the Rust-style separator, sugar for '/'
        parts = []
        while True:
            t = self.peek()
            if t[0] == "IDENT":
                if t[1] in ("as", "from"):
                    break
                parts.append(t[1]); self.next()
                nt = self.peek()
                if not (nt[0] == "SYM" and nt[1] in ("/", ".", "-", ":")):
                    break
            elif t[0] == "SYM" and t[1] in ("/", ".", "-"):
                parts.append(t[1]); self.next()
            elif t[0] == "SYM" and t[1] == ":":
                nt = self.toks[self.pos + 1] if self.pos + 1 < len(self.toks) else ("EOF", None, 0)
                if nt[0] == "SYM" and nt[1] == ":":
                    parts.append("/"); self.next(); self.next()
                else:
                    break
            elif t[0] == "SYM" and t[1] == "*":
                # W025 stage 2: wildcard tail, `use a::b::*` carries as
                # "a/b/*"; the interpreter strips the `/*` and flat-binds the
                # target table's exports.
                parts.append("*"); self.next(); break
            elif t[0] == "STR":
                parts.append(t[1]); self.next()
                nt = self.peek()
                if not (nt[0] == "SYM" and nt[1] in ("/", ".", "-", ":")):
                    break
            else:
                break
        return "".join(parts)

    def assign_or_expr(self, w):
        t1 = self.toks[self.pos + 1] if self.pos + 1 < len(self.toks) else ("EOF", None, 0)
        if t1[0] == "SYM" and t1[1] == "=":
            self.next()  # name
            self.next()  # =
            self.eat_nl()  # Z-125 (item 1): '=' continuation
            v = self.expr()
            self.end_stmt()
            return ("assign", w, None, v)
        if t1[0] == "SYM" and t1[1] in ("+=", "-=", "*=", "/=", "%="):
            opmap = {"+=": "+", "-=": "-", "*=": "*", "/=": "/", "%=": "%"}
            self.next()  # name
            self.next()  # op=
            self.eat_nl()  # Z-125 (item 1): 'op=' continuation
            v = self.expr()
            self.end_stmt()
            return ("assign", w, opmap[t1[1]], v)
        # expression statement (possibly index/member assignment)
        e = self.expr()
        t = self.peek()
        # L1a: multiple assignment / swap, a, b = b, a
        if t[0] == "SYM" and t[1] == "," and e[0] in ("ident", "index", "member"):
            save = self.pos
            targets = [e]
            valid = True
            while self.peek() == ("SYM", ",", self.peek()[2]):
                self.next()
                te = self.expr()
                if te[0] not in ("ident", "index", "member"):
                    valid = False
                targets.append(te)
            if valid and self.peek() == ("SYM", "=", self.peek()[2]):
                self.next()
                self.eat_nl()  # Z-125 (item 1): '=' continuation
                values = [self.expr()]
                while self.peek() == ("SYM", ",", self.peek()[2]):
                    self.next()
                    values.append(self.expr())
                self.end_stmt()
                return ("multi", targets, values, False)
            self.pos = save
            self.note(self.peek()[2], 4, "expression statement not terminated; rest of line skipped")
            self.skip_line()
            self.end_stmt()
            return ("expr", e)
        if t[0] == "SYM" and t[1] == "=":
            self.next()
            self.eat_nl()  # Z-125 (item 1): '=' continuation
            v = self.expr()
            self.end_stmt()
            if e[0] == "index":
                return ("idx_assign", e[1], e[2], None, v)
            if e[0] == "member":
                return ("mem_assign", e[1], e[2], None, v)
            self.note(t[2], 4, "assignment target must be a name, index or member; value computed and dropped")
            return ("expr", e)
        if t[0] == "SYM" and t[1] in ("+=", "-=", "*=", "/=", "%="):
            opmap = {"+=": "+", "-=": "-", "*=": "*", "/=": "/", "%=": "%"}
            self.next()
            self.eat_nl()  # Z-125 (item 1): 'op=' continuation
            v = self.expr()
            self.end_stmt()
            if e[0] == "index":
                return ("idx_assign", e[1], e[2], opmap[t[1]], v)
            if e[0] == "member":
                return ("mem_assign", e[1], e[2], opmap[t[1]], v)
            if e[0] == "ident":
                return ("assign", e[1], opmap[t[1]], v)
            self.note(t[2], 4, "compound assignment target invalid; dropped")
            return ("expr", e)
        # same-line garbage check BEFORE terminator
        if not (t[0] in ("NL", "EOF") or (t[0] == "SYM" and t[1] in (";", "}"))):
            self.note(t[2], 4, "expression statement not terminated; rest of line skipped")
            self.skip_line()
        self.end_stmt()
        return ("expr", e)

    def block(self):
        if not (self.peek() == ("SYM", "{", self.peek()[2])):
            self.note(self.peek()[2], 4, "block without braces; single statement accepted")
            s = self.stmt()
            return [s] if s else []
        # #111 mirror: nested blocks share the 4096 budget
        if self.depth >= 4096:
            self.note(self.peek()[2], 4, "block nested deeper than 4096; truncated")
            bal = 0
            while self.pos < len(self.toks):
                k = self.toks[self.pos][0]
                v = self.toks[self.pos][1]
                if k == "SYM" and v == "{":
                    bal += 1
                elif k == "SYM" and v == "}":
                    bal -= 1
                    if bal == 0:
                        self.pos += 1
                        break
                self.pos += 1
            return []
        self.depth += 1
        self.next()
        out = []
        while True:
            self.eat_nl()
            t = self.peek()
            if t[0] == "SYM" and t[1] == "}":
                self.next(); break
            if t[0] == "EOF":
                self.note(t[2], 4, "block auto-closed at end of file")
                break
            before = self.pos
            s = self.stmt()
            if s is not None:
                out.append(s)
            if self.pos == before:
                self.note(t[2], 4, "token skipped")
                self.next()
        self.depth -= 1
        return out

    def skip_to_stmt_end(self):
        # Z-CAPWINDOW mirror of parser.rs skip_to_stmt_end: consume tokens
        # up to (and including) the next statement terminator, delimiter-
        # balanced; a closing delimiter at depth 0 stays visible to the
        # caller (the truncation containment for delimiter-less arms).
        depth = 0
        while self.pos < len(self.toks):
            k, v, _l = self.toks[self.pos]
            if k == "SYM" and v in ("(", "[", "{"):
                depth += 1
            elif k == "SYM" and v in (")", "]", "}"):
                if depth == 0:
                    return
                depth -= 1
            elif (k == "NL" or v == ";") and depth == 0:
                self.pos += 1
                return
            elif k == "EOF":
                return
            self.pos += 1

def describe_tok(t):
    """Mirror of src/lexer.rs Tok::describe (dx-r1) for the token shapes
    that can reach the pattern-wildcard arm."""
    kind, val = t[0], t[1]
    if kind == "IDENT":
        return f"identifier '{val}'"
    if kind == "INT":
        return f"number {val}"
    if kind == "FLOAT":
        return f"number {val}"
    if kind == "STR":
        return f'string "{val}"'
    if kind == "INTERP":
        return f'interpolated string "{val}"'
    if kind == "EOF":
        return "end of input"
    if kind == "NL":
        return "end of line"
    return f"'{val}'"
