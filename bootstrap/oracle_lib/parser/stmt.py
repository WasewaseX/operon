"""operon oracle: parser.stmt (split of bootstrap/oracle.py)."""

from ..lexer import MARKS, edit_distance
from ..values import Gene



class PStmt:

    def stmt(self):
        t = self.peek()
        if t[0] == "MARK":
            marks = []
            # loop-9: stacked marks with newlines/semis between them (the
            # dx-r6 newline bridge now applies BETWEEN marks too)
            while True:
                self.eat_nl()
                if self.peek()[0] != "MARK":
                    break
                m = self.next()[1]
                if m in MARKS:
                    marks.append(m)
                else:
                    wk = None
                    for k in MARKS:
                        if edit_distance(m, k) <= (1 if len(m) <= 4 else 2):
                            self.note(t[2], 3, f"wobble: '@{m}' repaired to '@{k}'")
                            wk = k
                            break
                    if wk:
                        marks.append(wk)
                    else:
                        self.note(t[2], 4, f"unknown mark '@{m}' skipped")
            # reg-bio-3 (C10): `@copies n` carries its dosage argument
            copies = 1
            if "copies" in marks:
                tt = self.peek()
                if tt[0] == "INT":
                    self.next()
                    if tt[1] < 1 or tt[1] > 64:
                        self.note(tt[2], 4, "gene dosage clamped to 1..=64 copies (a level is a concentration, not an amplifier)")
                    copies = min(max(tt[1], 1), 64)
                else:
                    self.note(tt[2], 4, "@copies needs an integer 1..=64; default 1")
            # loop-9 (F-5): @riboswitch ligand off|on threshold t, a cis
            # aptamer on this gene's own transcript (mirror of the Rust drain)
            riboswitch = None
            if "riboswitch" in marks:
                tt = self.peek()
                lig = tt[1] if tt[0] == "IDENT" else ""
                if lig:
                    self.next()
                else:
                    self.note(tt[2], 4, "@riboswitch needs a ligand name; mark ignored")
                cls = self.peek()
                on = None
                if lig and cls[0] == "IDENT" and cls[1] in ("on", "off"):
                    self.next()
                    on = cls[1] == "on"
                elif lig:
                    self.note(cls[2], 4, "@riboswitch needs 'on' or 'off'; mark ignored")
                threshold = 0.5
                if on is not None:
                    nt = self.peek()
                    if nt[0] == "IDENT" and nt[1] == "threshold":
                        self.next()
                        vt = self.peek()
                        if vt[0] in ("FLOAT", "INT"):
                            self.next()
                            threshold = min(max(float(vt[1]), 0.0), 1.0)
                        else:
                            self.note(vt[2], 4, "riboswitch threshold needs a number 0..=1; default 0.5")
                    riboswitch = (lig, on, threshold)
            # loop-9 (F-2): @burst kon koff, per-gene promoter identity
            burst = None
            if "burst" in marks:
                vals = [0.3, 0.1]
                got = 0
                while got < 2:
                    vt = self.peek()
                    if vt[0] in ("FLOAT", "INT") and not isinstance(vt[1], bool):
                        self.next()
                        vals[got] = min(max(float(vt[1]), 0.0), 1.0)
                        got += 1
                    else:
                        break
                if got < 2:
                    self.note(t[2], 4, "@burst needs kon and koff (0..=1); defaults 0.3/0.1")
                burst = (vals[0], vals[1])
            # W64: @deprecated("migration text", since="2.4") payload, metadata
            # only (mirror of the Rust mark arm): parse leniently, attach to
            # the gene tuple, never evaluate. Malformed shapes degrade to a
            # rung-4 note, the mark is dropped, the gene keeps parsing.
            deprecated = None
            if "deprecated" in marks:
                tt = self.peek()
                if tt == ("SYM", "(", tt[2]) or (tt[0] == "SYM" and tt[1] == "("):
                    self.next()
                    msg = ""
                    vt = self.peek()
                    if vt[0] == "STR":
                        self.next()
                        msg = vt[1]
                    else:
                        self.note(vt[2], 4, f"@deprecated needs a string message; mark skipped")
                    since = None
                    nt = self.peek()
                    if nt[0] == "SYM" and nt[1] == ",":
                        self.next()
                        st = self.peek()
                        if st[0] == "IDENT" and st[1] == "since":
                            self.next()
                            if self.peek()[0] == "SYM" and self.peek()[1] == "=":
                                self.next()
                            vt2 = self.peek()
                            if vt2[0] == "STR":
                                self.next()
                                since = vt2[1]
                        elif st[0] == "STR":
                            self.next()
                            since = st[1]
                        else:
                            self.note(st[2], 4, "@deprecated since needs a string; ignored")
                    et = self.peek()
                    if et[0] == "SYM" and et[1] == ")":
                        self.next()
                    else:
                        depth = 0
                        while True:
                            et = self.peek()
                            if et[0] == "SYM" and et[1] == "(":
                                depth += 1
                            elif et[0] == "SYM" and et[1] == ")":
                                self.next()
                                if depth == 0:
                                    break
                                depth -= 1
                                continue
                            elif et[0] in ("NL", "EOF"):
                                break
                            self.next()
                            continue
                        self.note(t[2], 4, "@deprecated payload auto-closed")
                    if msg:
                        deprecated = (msg, since)
                else:
                    self.note(t[2], 4, "@deprecated needs a migration string; mark skipped")
            self.eat_nl()
            if not self.expect_kw("gene"):
                self.note(t[2], 4, "mark must precede 'gene'; skipped line")
                self.skip_line()
                return None
            return self.gene_def(marks, copies, riboswitch, burst, deprecated)
        if t[0] == "SYM" and t[1] == "{":
            self.note(t[2], 4, "bare block treated as scoped statements")
            return ("block", self.block())
        if t[0] == "IDENT":
            return self.word_stmt(t[1])
        self.note(t[2], 4, f"unexpected token at statement position")
        self.next()
        return None

    def gene_def(self, marks, copies=1, riboswitch=None, burst=None, deprecated=None):
        # Z-CAPWINDOW: def line = the first token after `gene` (the name),
        # mirror of parser.rs parse_gene_def's def_line (A13/dx-r2).
        gline = self.peek()[2]
        ac = "acetylate" in marks
        me = "methylate" in marks
        m6 = "m6a" in marks
        # reg-bio-3 (C10): @copies dosage arrives via the mark-argument
        # parse (the clamps/notes mirror the Rust core op-for-op)
        name = None
        t = self.peek()
        if t[0] == "IDENT" and t[1] != "guard":
            name = t[1]
            self.next()
        # TYPED-MODE: declared generic type parameters, `gene first<T>(...)`
        # (mirror of parser.rs: `<` in signature position, ident list with
        # optional `: bound`).
        type_params = []
        t = self.peek()
        if t[0] == "SYM" and t[1] == "<" and name is not None:
            self.next()
            while True:
                self.eat_nl()
                t = self.peek()
                if t[0] == "SYM" and t[1] == ">":
                    self.next()
                    break
                if t[0] == "EOF":
                    self.note(t[2], 4, "type-parameter list auto-closed")
                    break
                if t[0] == "IDENT":
                    self.next()
                    bound = None
                    t2 = self.peek()
                    if t2[0] == "SYM" and t2[1] == ":":
                        self.next()
                        t3 = self.peek()
                        if t3[0] == "IDENT":
                            self.next()
                            bound = t3[1]
                        else:
                            self.note(t3[2], 4, "type bound is not a name; dropped")
                    type_params.append((t[1], bound))
                    self.eat_nl()
                    if self.peek()[0] == "SYM" and self.peek()[1] == ",":
                        self.next()
                else:
                    self.note(t[2], 4, f"'{t[1]}' is not a type parameter name; list auto-closed")
                    break
        # W01-s2: type parameter names shadow aliases inside the body's
        # annotations (mirror of parser.rs type_param_stack push/pop).
        for (p, _b) in type_params:
            self.type_param_stack.append(p)
        params = []
        param_anns = []
        if self.peek() == ("SYM", "(", self.peek()[2]):
            self.next()
            while True:
                self.eat_nl()
                t = self.peek()
                if t[0] == "SYM" and t[1] == ")":
                    self.next(); break
                if t[0] == "EOF":
                    self.note(t[2], 4, "parameter list auto-closed")
                    break
                before = self.pos
                pname = self.ident()
                # W01 (L2c): parameter annotation, `gene f(x: int) { }`
                ann = None
                if self.peek() == ("SYM", ":", self.peek()[2]):
                    self.next()
                    ann = self.type_ann()
                dflt = None
                if self.peek() == ("SYM", "=", self.peek()[2]):
                    self.next()
                    dflt = self.expr()
                params.append((pname, dflt))
                param_anns.append(ann)
                if self.peek() == ("SYM", ",", self.peek()[2]):
                    self.next()
                if self.pos == before:
                    self.note(t[2], 4, "unclosed parameter list; auto-closed")
                    break
        # W01 (L2c): return annotation, `gene f(x) -> int { }`
        ret_ann = None
        if self.peek() == ("SYM", "->", self.peek()[2]):
            self.next()
            ret_ann = self.type_ann()
        guard = None
        self.eat_nl()
        if self.expect_kw("guard"):
            if self.peek() == ("SYM", "(", self.peek()[2]):
                self.next()
                cond = self.expr()
                if self.peek() == ("SYM", ")", self.peek()[2]):
                    self.next()
                else:
                    self.note(self.peek()[2], 4, "guard condition auto-closed")
                # Z-125 (item 5): the failure body must be a REAL brace
                # block (the `guard (c) { f }` form, else optional) —
                # ignoring the block check let block()'s single-statement
                # tolerance consume the NEXT statement as the failure body
                # (mirror of parser.rs).
                if self.expect_kw("else") or self.peek() == ("SYM", "{", self.peek()[2]):
                    gbody = self.block()
                    guard = (cond, gbody)
                else:
                    self.note(self.peek()[2], 4, "guard without failure body; empty failure body")
                    guard = (cond, [])
            else:
                self.note(self.peek()[2], 4, "guard without condition ignored")
        self.eat_nl()
        if self.peek() == ("SYM", "=>", self.peek()[2]):
            self.next()
            e = self.expr()
            self.end_stmt()
            for _p in type_params:
                self.type_param_stack.pop()
            return ("gene", Gene(name, params, guard, [("return", e)], ac, me, m6, copies, seq=False, riboswitch=riboswitch, burst=burst, param_anns=param_anns, ret_ann=ret_ann, type_params=type_params, line=gline))
        body = self.block()
        for _p in type_params:
            self.type_param_stack.pop()
        return ("gene", Gene(name, params, guard, body, ac, me, m6, copies, seq=False, riboswitch=riboswitch, burst=burst, param_anns=param_anns, ret_ann=ret_ann, type_params=type_params, line=gline))
