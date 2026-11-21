"""operon oracle: parser.expr (split of bootstrap/oracle.py)."""




class PExpr:

    # expressions
    def expr(self):
        cond = self.or_expr()
        t = self.peek()
        if t[0] == "SYM" and t[1] == "?":
            self.next()
            self.eat_nl()  # Z-125 (item 1): ternary continuation
            a = self.expr()
            t2 = self.peek()
            if t2[0] == "SYM" and t2[1] == ":":
                self.next()
                self.eat_nl()  # Z-125 (item 1): ternary continuation
            else:
                self.note(t[2], 4, "ternary missing ':'; else-branch is null")
            b = self.expr()
            return ("tern", cond, a, b)
        return cond

    def or_expr(self):
        left = self.nullish_expr()
        while True:
            t = self.peek()
            if (t[0] == "IDENT" and t[1] == "or") or (t[0] == "SYM" and t[1] == "||"):
                self.next()
                self.eat_nl()
                left = ("bin", "or", left, self.nullish_expr(), t[2])  # #125.8: op line (mirror of the Rust or_line fix)
            else:
                return left

    def nullish_expr(self):
        # L1a: a ?? b, sits between or and and (mirrors src/parser.rs)
        left = self.and_expr()
        while True:
            t = self.peek()
            if t[0] == "SYM" and t[1] == "??":
                self.next()
                self.eat_nl()
                left = ("bin", "nullish", left, self.and_expr(), t[2])  # W07: op line
            else:
                return left

    def and_expr(self):
        left = self.not_expr()
        while True:
            t = self.peek()
            if (t[0] == "IDENT" and t[1] == "and") or (t[0] == "SYM" and t[1] == "&&"):
                self.next()
                self.eat_nl()
                left = ("bin", "and", left, self.not_expr(), t[2])  # #125.8: op line (mirror of the Rust and_line fix)
            else:
                return left

    def not_expr(self):
        t = self.peek()
        if (t[0] == "IDENT" and t[1] == "not") or (t[0] == "SYM" and t[1] == "!"):
            self.next()
            return ("un", "not", self.not_expr())
        return self.cmp_expr()

    def cmp_expr(self):
        left = self.bitor_expr()
        while True:
            t = self.peek()
            if t[0] == "SYM" and t[1] in ("==", "!=", "<", "<=", ">", ">="):
                self.next()
                self.eat_nl()
                left = ("bin", t[1], left, self.bitor_expr(), t[2])
            elif t[0] == "IDENT" and t[1] == "in":
                self.next()
                self.eat_nl()
                left = ("bin", "in", left, self.bitor_expr(), t[2])
            else:
                return left

    def bitor_expr(self):
        left = self.bitxor_expr()
        while True:
            t = self.peek()
            if t[0] == "SYM" and t[1] == "|":
                self.next()
                self.eat_nl()
                left = ("bin", "|", left, self.bitxor_expr(), t[2])
            else:
                return left

    def bitxor_expr(self):
        left = self.bitand_expr()
        while True:
            t = self.peek()
            if t[0] == "SYM" and t[1] == "^":
                self.next()
                self.eat_nl()
                left = ("bin", "^", left, self.bitand_expr(), t[2])
            else:
                return left

    def bitand_expr(self):
        left = self.shift_expr()
        while True:
            t = self.peek()
            if t[0] == "SYM" and t[1] == "&":
                self.next()
                self.eat_nl()
                left = ("bin", "&", left, self.shift_expr(), t[2])
            else:
                return left

    def shift_expr(self):
        left = self.add_expr()
        while True:
            t = self.peek()
            if t[0] == "SYM" and t[1] in ("<<", ">>"):
                self.next()
                self.eat_nl()
                left = ("bin", t[1], left, self.add_expr(), t[2])
            else:
                return left

    def add_expr(self):
        left = self.mul_expr()
        while True:
            t = self.peek()
            if t[0] == "SYM" and t[1] in ("+", "-"):
                self.next()
                self.eat_nl()
                left = ("bin", t[1], left, self.mul_expr(), t[2])
            else:
                return left

    def mul_expr(self):
        left = self.unary()
        while True:
            t = self.peek()
            if t[0] == "SYM" and t[1] in ("*", "/", "//", "%"):
                self.next()
                self.eat_nl()
                left = ("bin", t[1], left, self.unary(), t[2])
            else:
                return left

    def unary(self):
        # Z-CAPWINDOW (L-053) mirror: the 4096-budget check moves from the
        # expression head (parser.rs parse_unary head, which fired one level
        # before every arm-entry check) to the Minus/Tilde arm entries —
        # pre-consume, pre-increment, matching parser.rs op-for-op. The
        # oracle previously charged NO depth on unary chains and never
        # tripped (Python native recursion ~150k) while the engine died at
        # 4095; both boundaries now coincide at arm-entry depth 4096
        # (N=4097 first trip) with the same skip-to-statement-end
        # containment and the same note text/line stamp.
        if self.peek() == ("SYM", "-", self.peek()[2]):
            if self.depth >= 4096:
                self.note(self.peek()[2], 4, "expression nested deeper than 4096; truncated")
                self.skip_to_stmt_end()
                return ("lit", None)
            self.next()
            self.depth += 1
            e = self.unary()
            self.depth -= 1
            return ("un", "neg", e)
        if self.peek() == ("SYM", "~", self.peek()[2]):
            if self.depth >= 4096:
                self.note(self.peek()[2], 4, "expression nested deeper than 4096; truncated")
                self.skip_to_stmt_end()
                return ("lit", None)
            self.next()
            self.depth += 1
            e = self.unary()
            self.depth -= 1
            return ("un", "bitnot", e)
        return self.pow_expr()

    def pow_expr(self):
        left = self.postfix()
        t = self.peek()
        if t[0] == "SYM" and t[1] == "**":
            self.next()
            self.eat_nl()  # Z-125: trailing ** continues onto the next line
            # right-assoc; right operand re-enters unary so 2**-3 parses
            return ("bin", "**", left, self.unary(), t[2])
        return left
