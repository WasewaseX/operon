"""operon oracle: parser.pat (split of bootstrap/oracle.py)."""

from ..parser.core import describe_tok



class PPat:

    # L1a: destructuring pattern parser (mirrors src/parser.rs parse_destructure_pat)
    def destructure_pat(self):
        t = self.peek()
        if t[0] == "SYM" and t[1] == "[":
            self.next()
            elems, rest = [], None
            while True:
                self.eat_nl()
                t2 = self.peek()
                if t2 == ("SYM", "]", t2[2]):
                    self.next(); break
                if t2[0] == "EOF":
                    self.note(t2[2], 4, "pattern bracket auto-closed")
                    break
                if t2 == ("SYM", "*", t2[2]):
                    self.next()
                    t3 = self.peek()
                    if t3[0] == "IDENT":
                        self.next()
                        rest = t3[1]
                    else:
                        self.note(t3[2], 4, "'*' in pattern needs a name; tail skipped")
                elif t2 == ("SYM", ",", t2[2]):
                    self.next()
                else:
                    elems.append(self.destructure_pat())
            return ("plist", elems, rest)
        if t[0] == "SYM" and t[1] == "{":
            self.next()
            keys = []
            while True:
                self.eat_nl()
                t2 = self.peek()
                if t2 == ("SYM", "}", t2[2]):
                    self.next(); break
                if t2[0] == "EOF":
                    self.note(t2[2], 4, "pattern brace auto-closed")
                    break
                if t2 == ("SYM", ",", t2[2]):
                    self.next()
                elif t2[0] == "IDENT":
                    self.next()
                    keys.append(t2[1])
                else:
                    self.note(t2[2], 4, f"'{t2[1]}' is not a map-pattern key; skipped")
                    self.next()
            return ("pmap", keys)
        t2 = self.peek()
        if t2[0] == "IDENT":
            self.next()
            return ("pbind", t2[1])
        self.note(t2[2], 4, f"'{t2[1]}' cannot start a pattern; binding null")
        self.next()
        return ("pbind", "_")

    # W01 (L2c): type-annotation grammar, `name`, `name?` (optional),
    # `a | b` (union). Malformed annotation degrades to any (Total Grammar).
    def type_ann(self):
        first = self.type_ann_atom()
        t = self.peek()
        if t[0] == "SYM" and t[1] == "|":
            alts = [first]
            while t[0] == "SYM" and t[1] == "|":
                self.next()
                alts.append(self.type_ann_atom())
                t = self.peek()
            return ("union", alts)
        return first

    def type_ann_atom(self):
        t = self.peek()
        if t[0] == "IDENT":
            self.next()
            # TYPED-MODE: generic annotation, `list[int]`, `map[str, int]`
            # (mirror of parser.rs type-args in annotation position).
            t2 = self.peek()
            if t2[0] == "SYM" and t2[1] == "[":
                self.next()
                args = []
                while True:
                    self.eat_nl()
                    t3 = self.peek()
                    if t3[0] == "SYM" and t3[1] == "]":
                        self.next()
                        break
                    if t3[0] == "EOF":
                        self.note(t3[2], 4, "type-argument list auto-closed")
                        break
                    args.append(self.type_ann())
                    self.eat_nl()
                    if self.peek()[0] == "SYM" and self.peek()[1] == ",":
                        self.next()
                return ("generic", t[1], args)
            if t2[0] == "SYM" and t2[1] == "?":
                self.next()
                return ("opt", self.type_ann_atom_resolved(t[1]))
            return self.type_ann_atom_resolved(t[1])
        self.note(t[2], 4, f"'{t[1]}' is not a type name; annotation treated as any")
        self.next()
        return ("named", "any")

    def type_ann_atom_resolved(self, w):
        # W01-s2 (mirror of parser.rs): a declared alias resolves at parse
        # time; an enclosing gene's type parameter never does.
        if any(p == w for p in self.type_param_stack):
            return ("named", w)
        for (n, target) in self.type_aliases:
            if n == w:
                return ("alias", n, target)
        return ("named", w)

    def pattern(self):
        # W02 (match-v2) mirror of parser.rs parse_pattern: atom | or-chain |
        # guard, with the legacy literal comma-run kept verbatim. Total
        # Grammar: a malformed pattern degrades to wildcard/bind + note.
        first = self.pattern_atom()
        # Legacy literal comma-run, only for a leading literal; a
        # non-literal in the run discards the collected literals (legacy
        # edge behavior preserved op-for-op with the Rust core).
        if first[0] == "lit":
            t = self.peek()
            if t[0] == "SYM" and t[1] == ",":
                lits = [first]
                while True:
                    t = self.peek()
                    if not (t[0] == "SYM" and t[1] == ","):
                        break
                    self.next()
                    t2 = self.peek()
                    neg2 = t2[0] == "SYM" and t2[1] == "-"
                    if neg2:
                        self.next()
                        t2 = self.peek()
                    if t2[0] in ("INT", "FLOAT"):
                        self.next()
                        lits.append(("lit", -t2[1] if neg2 else t2[1]))
                    elif t2[0] == "STR" and not neg2:
                        self.next()
                        lits.append(("lit", t2[1]))
                    else:
                        return self.pattern_atom()
                return lits[0] if len(lits) == 1 else ("multi", lits)
        # Or-pattern chain: `p1 | p2 | ...`, newlines allowed before any
        # alternative (multi-line chains), mirror of parser.rs.
        while self.peek()[0] == "NL":
            self.next()
        t = self.peek()
        if t[0] == "SYM" and t[1] == "|":
            alts = [first]
            while True:
                while self.peek()[0] == "NL":
                    self.next()
                t = self.peek()
                if not (t[0] == "SYM" and t[1] == "|"):
                    break
                self.next()
                alts.append(self.pattern_atom())
                while self.peek()[0] == "NL":
                    self.next()
            pat = ("or", alts)
        else:
            pat = first
        # Guarded arm: `pat if cond`, applies to the WHOLE or-chain.
        if self.at_ident("if"):
            self.next()
            cond = self.expr()
            return ("guard", pat, cond)
        return pat

    def pattern_atom(self):
        # #111 mirror: pattern recursion shares the 4096 budget
        if self.depth >= 4096:
            self.note(self.peek()[2], 4, "pattern nested deeper than 4096; truncated")
            return ("lit", None)
        self.depth += 1
        p = self.pattern_atom_inner()
        self.depth -= 1
        return p

    def pattern_atom_inner(self):
        t = self.peek()
        neg = t[0] == "SYM" and t[1] == "-"
        if neg:
            self.next()
            t = self.peek()
        if t[0] in ("INT", "FLOAT"):
            self.next()
            return ("lit", -t[1] if neg else t[1])
        if t[0] == "STR":
            # W02 parity fix: '-' before a string pattern is ignored with a
            # note (was: oracle said "dangling '-'" and went wildcard while
            # the Rust core kept the literal, latent corner divergence,
            # closed by mirroring the Rust behavior).
            if neg:
                self.note(t[2], 4, "'-' before a string pattern ignored")
            self.next()
            return ("lit", t[1])
        if t[0] == "SYM" and t[1] == "[" and not neg:
            self.next()
            elems = []
            rest = None
            while True:
                while self.peek()[0] == "NL":
                    self.next()
                t2 = self.peek()
                if t2[0] == "SYM" and t2[1] == "]":
                    self.next()
                    break
                if t2[0] == "EOF":
                    self.note(t2[2], 4, "pattern bracket auto-closed")
                    break
                if t2[0] == "SYM" and t2[1] == "*":
                    self.next()
                    t3 = self.peek()
                    if t3[0] == "IDENT":
                        self.next()
                        rest = t3[1]
                    else:
                        self.note(t3[2], 4, "'*' in pattern needs a name; tail skipped")
                elif t2[0] == "SYM" and t2[1] == ",":
                    self.next()
                else:
                    elems.append(self.pattern_atom())
            return ("list", elems, rest)
        if t[0] == "SYM" and t[1] == "{" and not neg:
            self.next()
            keys = []
            while True:
                while self.peek()[0] == "NL":
                    self.next()
                t2 = self.peek()
                if t2[0] == "SYM" and t2[1] == "}":
                    self.next()
                    break
                if t2[0] == "EOF":
                    self.note(t2[2], 4, "pattern brace auto-closed")
                    break
                if t2[0] == "SYM" and t2[1] == ",":
                    self.next()
                elif t2[0] == "IDENT":
                    self.next()
                    sub = None
                    t3 = self.peek()
                    if t3[0] == "SYM" and t3[1] == ":":
                        self.next()
                        sub = self.pattern_atom()
                    keys.append((t2[1], sub))
                else:
                    self.note(t2[2], 4, f"'{t2[1]}' is not a map-pattern key; skipped")
                    self.next()
            return ("map", keys)
        if t[0] == "IDENT" and not neg:
            if t[1] == "_":
                self.next()
                return ("wild",)
            if t[1] in ("true", "false"):
                self.next()
                return ("lit", t[1] == "true")
            if t[1] == "null":
                self.next()
                return ("null",)
            if t[1] in ("Some", "None", "Ok", "Err"):
                self.next()
                payload = None
                t2 = self.peek()
                if t2[0] == "SYM" and t2[1] == "(":
                    self.next()
                    line = t2[2]
                    t3 = self.peek()
                    if t3[0] == "SYM" and t3[1] == ")":
                        self.next()
                        self.note(line, 4, "empty variant payload pattern, treated as tag-only")
                    else:
                        payload = self.pattern_atom()
                        t3 = self.peek()
                        if t3[0] == "SYM" and t3[1] == ",":
                            self.note(
                                line, 4,
                                "variant payload is a single value; extra pattern elements ignored",
                            )
                            while not (
                                (self.peek()[0] == "SYM" and self.peek()[1] == ")")
                                or self.peek()[0] == "EOF"
                            ):
                                self.next()
                        t3 = self.peek()
                        if t3[0] == "SYM" and t3[1] == ")":
                            self.next()
                        else:
                            self.note(self.peek()[2], 4, "variant payload pattern auto-closed")
                return ("variant", t[1], payload)
            if t[1][:1].isupper():
                # Unknown capitalized tag: soft fallback to a binding. A
                # parenthesized payload is consumed and ignored so the token
                # stream stays aligned (mirror of parser.rs).
                self.note(t[2], 4, f"unknown variant tag '{t[1]}', pattern treated as a binding")
                self.next()
                t2 = self.peek()
                if t2[0] == "SYM" and t2[1] == "(":
                    self.note(t[2], 4, "unknown tag payload ignored (bound as a whole)")
                    self.next()
                    if not (self.peek()[0] == "SYM" and self.peek()[1] == ")"):
                        self.pattern_atom()
                        t3 = self.peek()
                        if t3[0] == "SYM" and t3[1] == ",":
                            while not (
                                (self.peek()[0] == "SYM" and self.peek()[1] == ")")
                                or self.peek()[0] == "EOF"
                            ):
                                self.next()
                    if self.peek()[0] == "SYM" and self.peek()[1] == ")":
                        self.next()
                    else:
                        self.note(self.peek()[2], 4, "unknown tag payload auto-closed")
                return ("bind", t[1])
            self.next()
            return ("bind", t[1])
        if neg:
            self.note(t[2], 4, "dangling '-' in pattern treated as wildcard")
            self.next()
            return ("wild",)
        self.note(t[2], 4, f"pattern '{describe_tok(t)}' treated as wildcard")
        self.next()
        return ("wild",)
