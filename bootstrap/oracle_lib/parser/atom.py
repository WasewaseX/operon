"""operon oracle: parser.atom (split of bootstrap/oracle.py)."""

from ..lexer import VALUE_SYNONYMS, lex
from ..parser.core import describe_tok



class PAtom:

    def postfix(self):
        e = self.primary()
        while True:
            t = self.peek()
            if t == ("SYM", "(", t[2]):
                # #111 mirror: call args share the 4096 budget
                if self.depth >= 4096:
                    self.note(t[2], 4, "expression nested deeper than 4096; truncated")
                    bal = 0
                    while self.pos < len(self.toks):
                        k = self.toks[self.pos][0]
                        v = self.toks[self.pos][1]
                        if k == "SYM" and v == "(":
                            bal += 1
                        elif k == "SYM" and v == ")":
                            bal -= 1
                            if bal == 0:
                                self.pos += 1
                                break
                        self.pos += 1
                    e = ("call", e, [], t[2])
                    continue
                self.next()
                self.depth += 1
                args = []
                while True:
                    self.eat_nl()
                    t2 = self.peek()
                    if t2 == ("SYM", ")", t2[2]):
                        self.next(); break
                    if t2[0] == "EOF":
                        self.note(t2[2], 4, "call arguments auto-closed")
                        break
                    args.append(self.expr())
                    if self.peek() == ("SYM", ",", t2[2]):
                        self.next()
                self.depth -= 1
                e = ("call", e, args, t[2])  # W07: LParen line (Rust stamps before next())
            elif t == ("SYM", "[", t[2]):
                # #111 mirror: index args share the 4096 budget
                if self.depth >= 4096:
                    self.note(t[2], 4, "expression nested deeper than 4096; truncated")
                    bal = 0
                    while self.pos < len(self.toks):
                        k = self.toks[self.pos][0]
                        v = self.toks[self.pos][1]
                        if k == "SYM" and v == "[":
                            bal += 1
                        elif k == "SYM" and v == "]":
                            bal -= 1
                            if bal == 0:
                                self.pos += 1
                                break
                        self.pos += 1
                    e = ("index", e, ("lit", None), t[2])
                    continue
                self.next()
                self.depth += 1
                idx = self.expr()
                self.depth -= 1
                if self.peek() == ("SYM", "]", self.peek()[2]):
                    self.next()
                else:
                    self.note(self.peek()[2], 4, "index bracket auto-closed")
                e = ("index", e, idx, t[2])  # W07: LBrack line
            elif t == ("SYM", ".", t[2]):
                self.next()
                t2 = self.peek()
                if t2[0] == "IDENT":
                    self.next()
                    if self.peek() == ("SYM", "(", t2[2]):
                        self.next()
                        args = []
                        while True:
                            self.eat_nl()
                            t3 = self.peek()
                            if t3 == ("SYM", ")", t3[2]):
                                self.next(); break
                            if t3[0] == "EOF":
                                break
                            args.append(self.expr())
                            if self.peek() == ("SYM", ",", t3[2]):
                                self.next()
                        e = ("method", e, t2[1], args)
                    else:
                        e = ("member", e, t2[1])
                else:
                    self.note(t2[2], 4, "'.' followed by non-name; member skipped")
                    break
            elif t == ("SYM", "?!", t[2]):
                # W06 (D-014): `e?!`, Option/Result propagation, a postfix
                # operator (binds tighter than every binary op, repeats:
                # Some(Some(3))?!?! unwraps twice). Mirrors src/parser.rs
                # Tok::QuestionBang postfix arm.
                self.next()
                e = ("prop", e, t[2])
            elif t == ("SYM", "?.", t[2]):
                # L1a: optional chaining (mirrors src/parser.rs QuestionDot)
                self.next()
                t2 = self.peek()
                if t2[0] == "IDENT":
                    self.next()
                    if self.peek() == ("SYM", "(", t2[2]):
                        self.next()
                        args = []
                        while True:
                            self.eat_nl()
                            t3 = self.peek()
                            if t3 == ("SYM", ")", t3[2]):
                                self.next(); break
                            if t3[0] == "EOF":
                                break
                            args.append(self.expr())
                            if self.peek() == ("SYM", ",", t3[2]):
                                self.next()
                        e = ("method?", e, t2[1], args)
                    else:
                        e = ("member?", e, t2[1])
                else:
                    self.note(t2[2], 4, "'?.' followed by non-name; chain resolves to null")
                    e = ("member?", e, "")
                    break
            elif t[0] == "SYM" and t[1] == ":" and self.pos + 1 < len(self.toks) and self.toks[self.pos + 1][:2] == ("SYM", ":"):
                # W025 stage 2: `e::name` is the namespace spelling of
                # `e.name` (stage 1 made `::` a use-path separator; stage 2
                # lets qualified reads and calls ride the same spelling
                # through nested tables). Exactly sugar for the Dot arm
                # above, the AST is identical.
                self.next(); self.next()
                t2 = self.peek()
                if t2[0] == "IDENT":
                    self.next()
                    if self.peek() == ("SYM", "(", t2[2]):
                        self.next()
                        args = []
                        while True:
                            self.eat_nl()
                            t3 = self.peek()
                            if t3 == ("SYM", ")", t3[2]):
                                self.next(); break
                            if t3[0] == "EOF":
                                break
                            args.append(self.expr())
                            if self.peek() == ("SYM", ",", t3[2]):
                                self.next()
                        e = ("method", e, t2[1], args)
                    else:
                        e = ("member", e, t2[1])
                else:
                    self.note(t2[2], 4, "'::' followed by non-name; member skipped")
                    break
            else:
                return e

    def primary(self):
        t = self.next()
        kind, val, line = t
        if kind == "INT":
            return ("lit", val)
        if kind == "FLOAT":
            return ("lit", val)
        if kind == "STR":
            return ("lit", val)
        if kind == "BYTES":
            # W029 mirror: bytes literals are ordinary literal nodes carrying
            # a Python bytes value (native, so == / hashing / dict keys work)
            return ("lit", val)
        if kind == "INTERP":
            return self.build_interp(val, line)
        if t == ("SYM", "(", line):
            # #111 mirror: shared 4096 budget (parser.rs LParen arm)
            if self.depth >= 4096:
                self.note(line, 4, "expression nested deeper than 4096; truncated")
                bal = 1
                while self.pos < len(self.toks):
                    k = self.toks[self.pos][0]
                    v = self.toks[self.pos][1]
                    if k == "SYM" and v == "(":
                        bal += 1
                    elif k == "SYM" and v == ")":
                        bal -= 1
                        if bal == 0:
                            self.pos += 1
                            break
                    self.pos += 1
                return ("lit", None)
            self.depth += 1
            e = self.expr()
            self.depth -= 1
            if self.peek() == ("SYM", ")", self.peek()[2]):
                self.next()
            else:
                self.note(self.peek()[2], 4, "parenthesis auto-closed")
            return e
        if t == ("SYM", "[", line):
            # #111 mirror: shared 4096 budget (parser.rs LBrack arm)
            if self.depth >= 4096:
                self.note(line, 4, "expression nested deeper than 4096; truncated")
                bal = 1
                while self.pos < len(self.toks):
                    k = self.toks[self.pos][0]
                    v = self.toks[self.pos][1]
                    if k == "SYM" and v == "[":
                        bal += 1
                    elif k == "SYM" and v == "]":
                        bal -= 1
                        if bal == 0:
                            self.pos += 1
                            break
                    self.pos += 1
                return ("lit", None)
            self.depth += 1
            items = []
            while True:
                self.eat_nl()
                t2 = self.peek()
                if t2 == ("SYM", "]", t2[2]):
                    self.next(); break
                if t2[0] == "EOF":
                    self.note(t2[2], 4, "list auto-closed at end of file")
                    break
                items.append(self.expr())
                if self.peek() == ("SYM", ",", t2[2]):
                    self.next()
                elif not (self.peek() == ("SYM", "]", self.peek()[2])):
                    self.note(self.peek()[2], 4, "list items separated automatically")
            self.depth -= 1
            return ("list", items)
        if t == ("SYM", "{", line):
            # #112/#111 mirror: the map arm shares the budget AND balances it
            # on every exit (parser.rs leak class: += without -= was #112).
            if self.depth >= 4096:
                self.note(line, 4, "expression nested deeper than 4096; truncated")
                bal = 1
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
                return ("lit", None)
            self.depth += 1
            pairs = []
            while True:
                self.eat_nl()
                t2 = self.peek()
                if t2 == ("SYM", "}", t2[2]):
                    self.next(); break
                if t2[0] == "EOF":
                    self.note(t2[2], 4, "map literal auto-closed at end of file")
                    break
                if t2[0] == "IDENT":
                    self.next()
                    key = ("lit", t2[1])
                elif t2[0] == "STR":
                    self.next()
                    key = ("lit", t2[1])
                elif t2[0] == "BYTES":
                    # W029 mirror: bytes are legal map keys (scalar class)
                    self.next()
                    key = ("lit", t2[1])
                elif t2[0] == "INT":
                    self.next()
                    key = ("lit", t2[1])
                else:
                    self.note(t2[2], 4, "map key must be a name or string; key null")
                    self.next()
                    key = ("null",)
                if self.peek() == ("SYM", ":", self.peek()[2]):
                    self.next()
                else:
                    self.note(self.peek()[2], 4, "map entry missing ':'; value null")
                val = self.expr()
                pairs.append((key, val))
                if self.peek() == ("SYM", ",", self.peek()[2]):
                    self.next()
            self.depth -= 1
            return ("map", pairs)
        if kind == "IDENT":
            if val in ("true", "false"):
                if val not in ("true", "false"):
                    self.note(line, 2, f"synonym '{val}' repaired")
                return ("lit", val == "true")
            if val in VALUE_SYNONYMS:
                self.note(line, 2, f"synonym '{val}' repaired to '{'null' if VALUE_SYNONYMS[val] is None else str(VALUE_SYNONYMS[val]).lower()}'")
                v = VALUE_SYNONYMS[val]
                return ("lit", v)
            if val == "null":
                return ("null",)
            if val in ("gene", "fn", "func", "def", "lambda"):
                if val != "gene":
                    self.note(line, 2, f"synonym '{val}' repaired to 'gene'")
                s = self.gene_def([])
                return ("lambda", s[1])
            if val == "new":
                cname = self.ident()
                cargs = []
                if self.peek() == ("SYM", "(", self.peek()[2]):
                    self.next()
                    while True:
                        self.eat_nl()
                        t2 = self.peek()
                        if t2[0] == "SYM" and t2[1] == ")":
                            self.next(); break
                        if t2[0] == "EOF":
                            break
                        before = self.pos
                        cargs.append(self.expr())
                        if self.peek() == ("SYM", ",", self.peek()[2]):
                            self.next()
                        if self.pos == before:
                            self.note(t2[2], 4, "unclosed constructor argument list; auto-closed")
                            break
                return ("new", cname, cargs)
            if val == "for":
                var = self.ident()
                self.expect_kw("in")
                self.eat_nl()  # Z-125 (item 1): 'in' continuation
                it = self.expr()
                filt = None
                if self.at_ident("if"):
                    self.next()
                    filt = self.expr()
                self.expect_kw("collect")
                body = self.expr()
                return ("collect", var, it, filt, body)
            return ("ident", val)
        # Z-NOTEPARITY-1 (receipt item 3): rust renders the offending token
        # (parser.rs "unexpected token '{}' in expression") -- mirror via the
        # describe_tok mirror of Tok::describe.
        self.note(line, 4, f"unexpected token '{describe_tok(t)}' in expression; null substituted")
        return ("null",)

    def build_interp(self, raw, line):
        from ..parser import P
        parts = []
        lit = []
        i, n = 0, len(raw)
        while i < n:
            if raw[i] == "{":
                if lit:
                    parts.append(("lit", "".join(lit)))
                    lit = []
                depth, j = 1, i + 1
                expr_txt = []
                while j < n and depth > 0:
                    if raw[j] == "{":
                        depth += 1
                    elif raw[j] == "}":
                        depth -= 1
                        if depth == 0:
                            break
                    expr_txt.append(raw[j])
                    j += 1
                i = j + 1
                sub_toks, sub_notes = lex("".join(expr_txt))
                sub = P(sub_toks, [])
                e = sub.expr()
                for nt in sub.notes:
                    self.note(line, nt.rung, nt.message)
                for nt in sub_notes:
                    self.note(line, nt.rung, nt.message)
                parts.append(("expr", e))
            else:
                lit.append(raw[i])
                i += 1
        if lit:
            parts.append(("lit", "".join(lit)))
        return ("interp", parts)
