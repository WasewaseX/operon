"""operon oracle: parser.word (split of bootstrap/oracle.py)."""

from ..annot import ann_render
from ..lexer import ARMS, KEYWORDS, MARKS, SYNONYMS, edit_distance, wobble_keyword
from ..values import Gene, M64, Pheno, Trait, TraitM



class PWord:

    def word_stmt(self, w):
        t1 = self.toks[self.pos + 1] if self.pos + 1 < len(self.toks) else ("EOF", None, 0)
        expr_head = (t1[0] == "SYM" and t1[1] in ("=", "(", "[", ".", "+=", "-=", "*=", "/=", "%=",
            "==", "!=", "<", "<=", ">", ">=", "+", "-", "*", "/", "//", "%", "&&", "||", "??"))  # Z-125 (item 2)
        word = w
        # W01-s2: `type Name = ...` is the type-alias form; the repair to
        # 'phenotype' happens silently (the alias arm intercepts first).
        t2 = self.toks[self.pos + 2] if self.pos + 2 < len(self.toks) else ("EOF", None, 0)
        alias_head = (w == "type" and t1[0] == "IDENT"
                      and t2[0] == "SYM" and t2[1] == "=")
        word = self._ws_resolve(w, expr_head, alias_head, word)
        if word == "trait": return self._ws_trait()
        if word == "gene": return self._ws_gene()
        if word == "const": return self._ws_const()
        if word == "let": return self._ws_let()
        if word in ("if",): return self._ws_if()
        if word == "while": return self._ws_while()
        if word == "loop": return self._ws_loop()
        if word == "scope": return self._ws_scope()
        if word == "for": return self._ws_for()
        if word == "return": return self._ws_return()
        if word == "break": return self._ws_break()
        if word == "continue": return self._ws_continue()
        if word == "match": return self._ws_match()
        if word == "use": return self._ws_use()
        if word == "tad": return self._ws_tad()
        if word == "module": return self._ws_module(w)
        if word == "anchor": return self._ws_anchor()
        if word == "enhance": return self._ws_enhance()
        if word == "silence": return self._ws_silence()
        if word == "stress": return self._ws_stress()
        if word == "raise": return self._ws_raise()
        if word == "fate": return self._ws_fate()
        if word == "regulate": return self._ws_regulate()
        if word == "ligand": return self._ws_ligand()
        if word == "autoinducer": return self._ws_autoinducer()
        if word == "decoy": return self._ws_decoy()
        if word == "operon": return self._ws_operon()
        if word == "toggle": return self._ws_toggle()
        if word == "repressilator": return self._ws_repressilator()
        if word == "frame": return self._ws_frame()
        if word == "splice": return self._ws_splice()
        if word == "edit": return self._ws_edit()
        if word == "ires": return self._ws_ires()
        if word == "phenotype": return self._ws_phenotype()
        if word == "sequence": return self._ws_sequence()
        if word == "yield": return self._ws_yield()
        # bare-name definition: `main { ... }` / `route(req) { ... }` are
        # gene definitions, lookahead: NAME '{' or NAME '(' ... ')' '{'
        t1 = self.toks[self.pos + 1] if self.pos + 1 < len(self.toks) else ("EOF", None, 0)
        is_def = False
        if word not in KEYWORDS:
            if t1[0] == "SYM" and t1[1] == "{":
                is_def = True
            elif t1[0] == "SYM" and t1[1] == "(":
                j = self.pos + 1
                depth = 0
                n = len(self.toks)
                while j < n:
                    tk = self.toks[j]
                    if tk[0] == "SYM" and tk[1] == "(":
                        depth += 1
                    elif tk[0] == "SYM" and tk[1] == ")":
                        depth -= 1
                        if depth == 0:
                            j += 1
                            while j < n and self.toks[j][0] == "NL":
                                j += 1
                            is_def = j < n and self.toks[j][0] == "SYM" and self.toks[j][1] == "{"
                            break
                    elif tk[0] == "EOF":
                        break
                    j += 1
        if is_def: return self._ws_is_def(word)
        return self.assign_or_expr(w)

    def _ws_resolve(self, w, expr_head, alias_head, word):
        if w not in KEYWORDS and not expr_head:
            syn = SYNONYMS.get(w)
            if syn and syn in ARMS:
                if not alias_head:
                    self.note(self.peek()[2], 2, f"synonym '{w}' repaired to '{syn}'")
                word = syn
            else:
                wk = wobble_keyword(w)
                if wk and wk in ARMS:
                    self.note(self.peek()[2], 3, f"wobble: '{w}' repaired to keyword '{wk}'")
                    word = wk
        return word


    def _ws_trait(self, ):
        # W04 (SPEC 8b): `trait Name { gene m(); gene n() { ... } }`,
        # mirror of the Rust parser. A method with a body is a DEFAULT
        # (parsed by the normal gene parser); one without is REQUIRED.
        self.next()
        tname = self.ident()
        methods = []
        if self.peek() == ("SYM", "{", self.peek()[2]):
            self.next()
            while True:
                self.eat_nl()
                t = self.peek()
                if t[0] == "SYM" and t[1] == "}":
                    self.next(); break
                if t[0] == "EOF":
                    self.note(t[2], 4, "trait body auto-closed")
                    break
                if t[0] == "IDENT" and (t[1] == "gene" or SYNONYMS.get(t[1]) == "gene"):
                    if self._trait_method_has_body():
                        self.next()  # consume 'gene', gene_def parses from the name
                        g = self.gene_def([])
                        if g[0] == "gene":
                            methods.append(TraitM(g[1].name or "?", False, g[1]))
                        else:
                            self.note(t[2], 4, "trait method default body lost; treated as required")
                            methods.append(TraitM("?", True, None))
                    else:
                        self.next()
                        mname = self.ident()
                        self._trait_params()
                        self.end_stmt()
                        methods.append(TraitM(mname, True, None))
                    continue
                self.note(t[2], 4, "unexpected token in trait body; skipped")
                self.next()
        else:
            self.note(self.peek()[2], 4, "trait without body declares no methods")
        return ("trait", Trait(tname, methods))

    def _ws_gene(self, ):
        self.next()
        return self.gene_def([])

    def _ws_const(self, ):
        # W05: `const NAME = expr`, immutable binding with deep-freeze
        # semantics (mirror of the Rust parser; SPEC §7d).
        self.next()
        t = self.peek()
        if t[0] == "SYM" and t[1] in ("[", "{"):
            line = self.peek()[2]
            pat = self.destructure_pat()
            self.note(line, 4, "const destructuring not supported; bound as mutable let")
            if self.peek() == ("SYM", "=", self.peek()[2]):
                self.next()
                e = self.expr()
                self.end_stmt()
                return ("letpat", pat, e)
            self.note(self.peek()[2], 4, "destructured 'let' without value binds nulls")
            self.end_stmt()
            return ("letpat", pat, ("null",))
        name = self.ident()
        t2 = self.peek()
        if t2[0] == "SYM" and t2[1] == ":":
            line = t2[2]
            self.next()
            self.type_ann()
            self.note(line, 4, "const type annotation is not checked in v1; dropped")
        if self.peek() == ("SYM", "=", self.peek()[2]):
            self.next()
            e = self.expr()
            self.end_stmt()
            return ("const", name, e)
        self.note(self.peek()[2], 4, "const without '=' binds null")
        self.end_stmt()
        return ("const", name, ("null",))

    def _ws_let(self, ):
        self.next()
        # W05: contextual `mut` annotation, documentation-only in v2.x;
        # consumed silently when followed by the real name.
        t = self.peek()
        if t[0] == "IDENT" and t[1] == "mut":
            nxt = self.toks[self.pos + 1] if self.pos + 1 < len(self.toks) else None
            if nxt is not None and nxt[0] == "IDENT":
                self.next()
        t = self.peek()
        # L1a: destructuring definitions
        if t[0] == "SYM" and t[1] in ("[", "{"):
            pat = self.destructure_pat()
            if self.peek() == ("SYM", "=", self.peek()[2]):
                self.next()
                self.eat_nl()  # Z-125 (item 1): '=' continuation
                e = self.expr()
                self.end_stmt()
                return ("letpat", pat, e)
            self.note(self.peek()[2], 4, "destructured 'let' without value binds nulls")
            self.end_stmt()
            return ("letpat", pat, ("null",))
        name = self.ident()
        # L1a: `let a, b = 1, 2` multi-define
        if self.peek() == ("SYM", ",", self.peek()[2]):
            names = [name]
            while self.peek() == ("SYM", ",", self.peek()[2]):
                self.next()
                names.append(self.ident())
            if self.peek() == ("SYM", "=", self.peek()[2]):
                self.next()
                self.eat_nl()  # Z-125 (item 1): '=' continuation
                values = [self.expr()]
                while self.peek() == ("SYM", ",", self.peek()[2]):
                    self.next()
                    values.append(self.expr())
                self.end_stmt()
                return ("multi", [("ident", n) for n in names], values, True)
            self.note(self.peek()[2], 4, "multi 'let' without value binds nulls")
            self.end_stmt()
            return ("multi", [("ident", n) for n in names], [("null",)] * len(names), True)
        # W01 (L2c): soft type annotation, `let n: int = 3`
        t2 = self.peek()
        if t2[0] == "SYM" and t2[1] == ":":
            self.next()
            ann = self.type_ann()
            if self.peek() == ("SYM", "=", self.peek()[2]):
                self.next()
                self.eat_nl()  # Z-125 (item 1): '=' continuation
                e = self.expr()
                self.end_stmt()
                return ("letann", name, ann, e)
            self.note(self.peek()[2], 4, f"'let {name}: {ann_render(ann)}' without value binds null")
            self.end_stmt()
            return ("letann", name, ann, ("null",))
        if self.peek() == ("SYM", "=", self.peek()[2]):
            self.next()
            self.eat_nl()  # Z-125 (item 1): '=' continuation
            e = self.expr()
            self.end_stmt()
            return ("let", name, e)
        self.note(self.peek()[2], 4, f"'let {name}' without value binds null")
        self.end_stmt()
        return ("let", name, ("null",))

    def _ws_if(self, ):
        self.next()
        branches = [(self.expr(), self.block())]
        els = None
        while True:
            self.eat_nl()
            if self.at_ident("elif"):
                self.next()
                branches.append((self.expr(), self.block()))
            elif self.expect_kw("else"):
                els = self.block()
                break
            else:
                break
        return ("if", branches, els)

    def _ws_while(self, ):
        self.next()
        cond = self.expr()
        return ("while", cond, self.block())

    def _ws_loop(self, ):
        self.next()
        return ("loop", self.block())

    def _ws_scope(self, ):
        # W17: structured-concurrency block
        self.next()
        return ("scope", self.block())

    def _ws_for(self, ):
        for_line = self.peek()[2]
        self.next()
        t = self.peek()
        # L1a: destructuring loop target
        if t[0] == "SYM" and t[1] in ("[", "{"):
            pat = self.destructure_pat()
            if not self.expect_kw("in"):
                self.note(self.peek()[2], 4, "'for <pattern>' missing 'in'; iterating null")
            self.eat_nl()  # Z-125 (item 1): 'in' continuation
            it = self.expr()
            return ("forpat", pat, it, self.block())
        name = self.ident()
        if not self.expect_kw("in"):
            self.note(self.peek()[2], 4, f"'for {name}' missing 'in'; iterating null")
        self.eat_nl()  # Z-125 (item 1): 'in' continuation
        it = self.expr()
        # Z-125 (item 3): statement-position collect comprehension —
        # `for x in xs [if cond] collect expr` used to fall into the
        # no-braces block tolerance and silently lose the body. Same-line
        # only, mirroring parser.rs.
        tk = self.peek()
        if tk[0] == "IDENT" and tk[1] == "collect" and tk[2] == for_line:
            self.next()
            body = self.expr()
            self.end_stmt()
            return ("expr", ("collect", name, it, None, body))
        if tk[0] == "IDENT" and tk[1] == "if" and tk[2] == for_line:
            self.next()
            filt = self.expr()
            tk2 = self.peek()
            if tk2[0] == "IDENT" and tk2[1] == "collect":
                self.next()
                body = self.expr()
                self.end_stmt()
                return ("expr", ("collect", name, it, filt, body))
            self.note(self.peek()[2], 4, "'for' filter without 'collect'; line skipped")
            self.skip_line()
        return ("for", name, it, self.block())

    def _ws_return(self, ):
        self.next()
        k = self.peek()[0]
        if k in ("NL", "EOF") or (k == "SYM" and self.peek()[1] in (";", "}")):
            self.end_stmt()
            return ("return", ("null",))
        e = self.expr()
        self.end_stmt()
        return ("return", e)

    def _ws_break(self, ):
        self.next(); self.end_stmt(); return ("break",)

    def _ws_continue(self, ):
        self.next(); self.end_stmt(); return ("continue",)

    def _ws_match(self, ):
        self.next()
        subj = self.expr()
        cases = []
        if self.peek() == ("SYM", "{", self.peek()[2]):
            self.next()
            while True:
                self.eat_nl()
                t = self.peek()
                if t[0] == "SYM" and t[1] == "}":
                    self.next(); break
                if t[0] == "EOF":
                    self.note(t[2], 4, "match block auto-closed at end of file")
                    break
                if not self.expect_kw("case"):
                    self.note(t[2], 4, "expected 'case' in match; skipped token")
                    self.next(); continue
                pat = self.pattern()
                if self.peek() == ("SYM", "=>", t[2]):
                    self.next()
                    e = self.expr()
                    self.end_stmt()
                    body = [("expr", e)]
                else:
                    body = self.block()
                cases.append((pat, body))
        return ("match", subj, cases)

    def _ws_use(self, ):
        self.next()
        path = self.use_path()
        alias = None
        if self.expect_kw("as"):
            alias = self.ident()
        self.end_stmt()
        return ("use", path, alias)

    def _ws_tad(self, ):
        self.next()
        name = self.ident()
        return ("tad", name, self.block())

    def _ws_module(self, w):
        # W025 stage 2: nested sub-module declaration, CONTEXTUAL like the
        # Rust core: only `module NAME {` (newlines tolerated between the
        # words) is the declaration; every other use of the word `module`
        # stays an ordinary identifier (it is not in KEYWORDS).
        n_toks = len(self.toks)
        j = self.pos + 1
        while j < n_toks and (self.toks[j][0] == "NL" or self.toks[j][:2] == ("SYM", ";")):
            j += 1
        is_decl = j < n_toks and self.toks[j][0] == "IDENT"
        if is_decl:
            j += 1
            while j < n_toks and (self.toks[j][0] == "NL" or self.toks[j][:2] == ("SYM", ";")):
                j += 1
            is_decl = j < n_toks and self.toks[j][:2] == ("SYM", "{")
        if not is_decl:
            return self.assign_or_expr(w)
        self.next()
        name = self.ident()
        while self.peek()[0] == "NL":
            self.next()
        return ("module", name, self.block())

    def _ws_anchor(self, ):
        self.next()
        is_export = self.expect_kw("export")
        if not is_export:
            self.expect_kw("import")
        names = [self.ident()]
        while self.peek() == ("SYM", ",", self.peek()[2]):
            self.next()
            names.append(self.ident())
        self.end_stmt()
        return ("anchor_export" if is_export else "anchor_import", [n for n in names if n])

    def _ws_enhance(self, ):
        self.next()
        names = [self.ident()]
        while self.peek() == ("SYM", ",", self.peek()[2]):
            self.next()
            names.append(self.ident())
        self.end_stmt()
        return ("enhance", [n for n in names if n])

    def _ws_silence(self, ):
        # reg-bio-3 (C9): stoichiometric RISC, strength/sites
        self.next()
        frm = self.ident()
        to = None
        if self.peek() == ("SYM", "->", self.peek()[2]):
            self.next()
            to = self.ident()
        strength, sites = 1.0, 1
        t2 = self.peek()
        if t2[0] == "IDENT" and t2[1] == "strength":
            self.next()
            tt = self.peek()
            if tt[0] in ("INT", "FLOAT"):
                strength = min(max(float(tt[1]), 0.0), 1.0)
                self.next()
            else:
                self.note(tt[2], 4, "strength needs a number 0..=1; ignored")
        t2 = self.peek()
        if t2[0] == "IDENT" and t2[1] == "sites":
            self.next()
            tt = self.peek()
            if tt[0] == "INT":
                if tt[1] < 1 or tt[1] > 64:
                    self.note(tt[2], 4, "sites clamped to 1..=64")
                sites = min(max(tt[1], 1), 64)
                self.next()
            else:
                self.note(tt[2], 4, "sites needs an integer 1..=64; ignored")
        self.end_stmt()
        return ("silence", frm, to, strength, sites)

    def _ws_stress(self, ):
        self.next()
        kind = None
        t = self.peek()
        nt = self.toks[self.pos + 1] if self.pos + 1 < len(self.toks) else ("EOF", None, 0)
        if t[0] == "IDENT" and nt == ("SYM", "{", t[2]):
            kind = t[1]
            self.next()
        body = self.block()
        rescue = None
        self.eat_nl()
        if self.expect_kw("rescue"):
            bind = None
            if self.peek() == ("SYM", "(", self.peek()[2]):
                self.next()
                if self.peek()[0] == "IDENT":
                    bind = self.next()[1]
                if self.peek() == ("SYM", ")", self.peek()[2]):
                    self.next()
            rescue = (bind, self.block())
        return ("stress", kind, body, rescue)

    def _ws_raise(self, ):
        self.next()
        save = self.pos
        t = self.peek()
        if t[0] == "IDENT" and t[1] in ("unfolded", "missing", "overflow", "burned", "interference"):
            self.next()
            if self.peek() == ("SYM", ",", t[2]):
                self.next()
                e = self.expr()
                self.end_stmt()
                return ("raise", t[1], e)
            self.pos = save
        e = self.expr()
        self.end_stmt()
        return ("raise", None, e)

    def _ws_fate(self, ):
        self.next()
        name = self.ident()
        states, enter = [], None
        if self.peek() == ("SYM", "{", self.peek()[2]):
            self.next()
            while True:
                self.eat_nl()
                t = self.peek()
                if t[0] == "SYM" and t[1] == "}":
                    self.next(); break
                if t[0] == "EOF":
                    break
                if t[0] == "IDENT" and (t[1] == "state" or edit_distance(t[1], "state") <= 1):
                    if t[1] != "state":
                        self.note(t[2], 3, f"wobble: '{t[1]}' repaired to 'state'")
                    self.next()
                    frm = self.ident()
                    targets = []
                    if self.peek() == ("SYM", "->", t[2]):
                        self.next()
                        targets.append(self.ident())
                        while self.peek() == ("SYM", ",", t[2]):
                            self.next()
                            targets.append(self.ident())
                    states.append((frm, [x for x in targets if x]))
                    self.end_stmt()
                elif t[0] == "IDENT" and (t[1] == "enter" or edit_distance(t[1], "enter") <= 1):
                    if t[1] != "enter":
                        self.note(t[2], 3, f"wobble: '{t[1]}' repaired to 'enter'")
                    self.next()
                    enter = self.ident()
                    self.end_stmt()
                else:
                    self.note(t[2], 4, "unexpected token in fate block; skipped")
                    self.next()
        return ("fate", name, states, enter)

    def _ws_regulate(self, ):
        self.next()
        edges, trans, binds = [], [], []
        if self.peek() == ("SYM", "{", self.peek()[2]):
            self.next()
            while True:
                self.eat_nl()
                t = self.peek()
                if t[0] == "SYM" and t[1] == "}":
                    self.next(); break
                if t[0] == "EOF":
                    break
                if t[0] != "IDENT":
                    self.note(t[2], 4, "unexpected token in regulate block; skipped")
                    self.next(); continue
                frm = self.next()[1]
                # reg-bio-2 (C1): `a translates b rate r decay d;`
                if self.expect_kw("translates"):
                    to = self.ident()
                    rate = None
                    if self.expect_kw("rate"):
                        tt = self.peek()
                        if tt[0] in ("INT", "FLOAT"):
                            rate = float(tt[1])
                            self.next()
                        else:
                            self.note(tt[2], 4, "rate needs a number; using 1.0")
                    pdecay = None
                    if self.expect_kw("decay"):
                        tt = self.peek()
                        if tt[0] in ("INT", "FLOAT"):
                            pdecay = min(max(float(tt[1]), 0.0), 1.0)
                            self.next()
                        else:
                            self.note(tt[2], 4, "decay needs a number; ignored")
                    trans.append((frm, to, rate, pdecay))
                    self.end_stmt()
                    continue
                # reg-bio-2 (A4): `bind tf inducer lg k v;`, `bind` is a
                # HEAD keyword here (no edge source); head already consumed.
                if frm == "bind":
                    tf = self.ident()
                    inducer = None
                    if self.expect_kw("inducer"):
                        inducer = True
                    elif self.expect_kw("cofactor"):
                        inducer = False
                    if inducer is None:
                        self.note(t[2], 4, "bind needs 'inducer' or 'cofactor'; binding dropped")
                        self.skip_line(); continue
                    lg = self.ident()
                    k = 0.1
                    if self.expect_kw("k"):
                        tt = self.peek()
                        if tt[0] in ("INT", "FLOAT"):
                            k = float(tt[1])
                            self.next()
                        else:
                            self.note(tt[2], 4, "k needs a number; using 0.1")
                        if k <= 0.0:
                            self.note(tt[2], 4, "k must be > 0; using 0.1")
                            k = 0.1
                    binds.append((tf, lg, inducer, k))
                    self.end_stmt()
                    continue
                # reg-bio-2 (A5): per-edge attenuator flag
                attenuating = False
                inhibit = None
                if self.expect_kw("activates"):
                    inhibit = False
                elif self.expect_kw("inhibits"):
                    inhibit = True
                elif self.expect_kw("attenuates"):
                    attenuating = True
                    inhibit = True
                if inhibit is None:
                    self.note(t[2], 4, "regulate edge missing 'activates'/'inhibits'/'translates'; edge dropped")
                    self.skip_line(); continue
                self._ws_regulate_edge(frm, t, edges, inhibit, attenuating)
        return ("regulate", edges, trans, binds)

    def _ws_regulate_edge(self, frm, t, edges, inhibit, attenuating):
                to = self.ident()
                strength = 1.0
                if self.expect_kw("strength"):
                    tt = self.peek()
                    if tt[0] in ("INT", "FLOAT"):
                        strength = float(tt[1]) if tt[0] == "FLOAT" else float(tt[1])
                        self.next()
                    else:
                        self.note(tt[2], 4, "strength needs a number; using 1.0")
                    # reg-bio-2 (D2c): strength clamps to the physical
                    # range (mirror of the Rust parser clamp + note).
                    if strength > 1.0:
                        self.note(tt[2], 4, "strength > 1.0 clamped to 1.0 (levels are concentration fractions)")
                        strength = 1.0
                    elif strength < 0.0:
                        self.note(tt[2], 4, "negative strength clamped to 0.0 (a negative repressor is not a booster)")
                        strength = 0.0
                threshold = None
                if self.expect_kw("threshold"):
                    tt = self.peek()
                    if tt[0] in ("INT", "FLOAT"):
                        threshold = float(tt[1])
                        self.next()
                    else:
                        self.note(tt[2], 4, "threshold needs a number; ignored")
                # reg-bio (F-2): optional per-edge Hill exponent (1..=8)
                hill = None
                if self.expect_kw("hill"):
                    tt = self.peek()
                    if tt[0] == "INT":
                        iv = int(tt[1])
                        self.next()
                        if 1 <= iv <= 8:
                            hill = iv
                        else:
                            self.note(tt[2], 4, "hill needs an integer 1..=8; edge keeps the default n=2 shape")
                    else:
                        self.note(tt[2], 4, "hill needs an integer 1..=8; edge keeps the default n=2 shape")
                # reg-bio (F-3): optional cis-regulatory OR membership
                is_any = False
                if self.expect_kw("any"):
                    is_any = True
                # reg-bio-2 (D2b/B7): occupancy + pooling keywords
                # (canonical order: strength -> threshold -> hill -> any -> occupy -> sum)
                occupy = False
                if self.expect_kw("occupy"):
                    occupy = True
                is_sum = False
                if self.expect_kw("sum"):
                    is_sum = True
                if (hill is not None or is_any) and threshold is None:
                    self.note(tt[2], 4, "hill/any apply to thresholded edges; ignored (edge stays declarative)")
                    hill = None
                    is_any = False
                if is_any and inhibit:
                    self.note(tt[2], 4, "any on an inhibiting edge is ignored (inhibitors already veto independently)")
                    is_any = False
                if occupy and not inhibit:
                    self.note(tt[2], 4, "occupy applies to inhibiting edges; ignored (activators cannot occupy a promoter they activate)")
                    occupy = False
                if is_sum and (inhibit or threshold is None):
                    self.note(tt[2], 4, "sum applies to thresholded activating edges; ignored")
                    is_sum = False
                edges.append((frm, to, strength, inhibit, threshold, hill, is_any, occupy, is_sum, attenuating))
                self.end_stmt()


    def _ws_ligand(self, ):
        # reg-bio-2 (A4): `ligand iptg;`, a small-molecule pool
        self.next()
        name = self.ident()
        self.end_stmt()
        return ("ligand", name)

    def _ws_autoinducer(self, ):
        # loop-9 (C8): `autoinducer ahl;`, register a quorum-sensing
        # signal species into the shared medium (parse mirror)
        self.next()
        name = self.ident()
        self.end_stmt()
        return ("autoinducer", name)

    def _ws_decoy(self, ):
        # reg-bio-2 (C11): `decoy d for tf capacity 0.5;`
        self.next()
        d = self.ident()
        tf, cap = "", 0.0
        if self.expect_kw("for"):
            tf = self.ident()
            t2 = self.peek()
            if t2[0] == "IDENT" and t2[1] == "capacity":
                self.next()
                tt = self.peek()
                if tt[0] in ("INT", "FLOAT"):
                    cap = min(max(float(tt[1]), 0.0), 1.0)
                    self.next()
                else:
                    self.note(tt[2], 4, "capacity needs a number 0..=1; ignored")
                    cap = 0.0
            else:
                self.note(t2[2], 4, "decoy needs 'capacity <num>'; declared inert")
        else:
            self.note(self.peek()[2], 4, "decoy needs 'for <tf> capacity <num>'; skipped")
        self.end_stmt()
        return ("decoy", d, tf, cap)

    def _ws_operon(self, ):
        # reg-bio-3 (A1/A7): polycistronic transcription unit,
        # `operon lac { lacZ rbs 1.0; lacY rbs 0.6; lacA; }` (mirror)
        self.next()
        name = self.ident()
        members = []
        if self.peek() == ("SYM", "{", self.peek()[2]):
            self.next()
            while True:
                self.eat_nl()
                t2 = self.peek()
                if t2 == ("SYM", "}", t2[2]):
                    self.next()
                    break
                if t2[0] == "EOF":
                    self.note(t2[2], 4, "operon block auto-closed")
                    break
                if t2[0] == "IDENT":
                    self.next()
                    rbs = 1.0
                    t3 = self.peek()
                    if t3[0] == "IDENT" and t3[1] == "rbs":
                        self.next()
                        tt = self.peek()
                        if tt[0] in ("INT", "FLOAT"):
                            rbs = min(max(float(tt[1]), 0.0), 1.0)
                            self.next()
                        else:
                            self.note(tt[2], 4, "rbs needs a number 0..=1; using 1.0")
                    members.append((t2[1], rbs))
                    self.end_stmt()
                else:
                    self.note(t2[2], 4, "unexpected token in operon block; skipped")
                    self.next()
        else:
            self.note(self.peek()[2], 4, "operon needs a block '{ cistron rbs r; ... }'; skipped")
        return ("operon", name, members)

    def _ws_toggle(self, ):
        self.next()
        a = self.ident()
        b = a
        if self.peek() == ("SYM", ",", self.peek()[2]):
            self.next()
            b = self.ident()
        self.end_stmt()
        return ("toggle", a, b)

    def _ws_repressilator(self, ):
        self.next()
        ring = [self.ident()]
        while self.peek() == ("SYM", "->", self.peek()[2]):
            self.next()
            ring.append(self.ident())
        period = None
        if self.expect_kw("period"):
            t = self.peek()
            if t[0] in ("INT", "FLOAT"):
                period = float(t[1])
                self.next()
        # reg-bio (F-5): inline kinetics, mirror of the Rust parser.
        # Canonical order: alpha, gamma, hill, basal, noise, seed.
        ov = {"alpha": None, "gamma": None, "hill": None, "basal": None,
              "noise": None, "seed": None}
        self._ws_repressi_opts(ov)
        self.end_stmt()
        return ("repressilator", [r for r in ring if r], period, ov)

    def _ws_repressi_opts(self, ov):
        while True:
            if self.expect_kw("alpha"):
                t = self.peek()
                if t[0] in ("INT", "FLOAT"):
                    self.next()
                    f = float(t[1])
                    if f > 0.0:
                        ov["alpha"] = f
                    else:
                        self.note(t[2], 4, "alpha needs a number > 0; ignored")
                else:
                    self.note(t[2], 4, "alpha needs a number > 0; ignored")
            elif self.expect_kw("gamma"):
                t = self.peek()
                if t[0] in ("INT", "FLOAT"):
                    self.next()
                    f = float(t[1])
                    if f >= 0.0:
                        ov["gamma"] = f
                    else:
                        self.note(t[2], 4, "gamma needs a number >= 0; ignored")
                else:
                    self.note(t[2], 4, "gamma needs a number >= 0; ignored")
            elif self.expect_kw("hill"):
                t = self.peek()
                if t[0] == "INT":
                    self.next()
                    iv = int(t[1])
                    if 1 <= iv <= 8:
                        ov["hill"] = iv
                    else:
                        self.note(t[2], 4, "hill needs an integer 1..=8; ignored")
                else:
                    self.note(t[2], 4, "hill needs an integer 1..=8; ignored")
            elif self.expect_kw("basal"):
                t = self.peek()
                if t[0] in ("INT", "FLOAT"):
                    self.next()
                    f = float(t[1])
                    if f >= 0.0:
                        ov["basal"] = f
                    else:
                        self.note(t[2], 4, "basal needs a number >= 0; ignored")
                else:
                    self.note(t[2], 4, "basal needs a number >= 0; ignored")
            elif self.expect_kw("noise"):
                t = self.peek()
                if t[0] in ("INT", "FLOAT"):
                    self.next()
                    f = float(t[1])
                    if 0.0 <= f <= 1.0:
                        ov["noise"] = f
                    else:
                        self.note(t[2], 4, "noise needs a number in 0..=1; ignored")
                else:
                    self.note(t[2], 4, "noise needs a number in 0..=1; ignored")
            elif self.expect_kw("seed"):
                t = self.peek()
                if t[0] == "INT":
                    self.next()
                    iv = int(t[1])
                    ov["seed"] = 0x9E3779B97F4A7C15 if iv == 0 else (iv & M64)
                else:
                    self.note(t[2], 4, "seed needs an integer; ignored")
            else:
                break


    def _ws_frame(self, ):
        self.next()
        is_proof = self.expect_kw("proof")
        name = "proof" if is_proof else self.ident()
        return ("frame", name, is_proof, self.block())

    def _ws_splice(self, ):
        self.next()
        root = self.ident()
        variants = []
        pending_marks = []  # T2c: marks before 'variant' apply to that variant
        if self.peek() == ("SYM", "{", self.peek()[2]):
            self.next()
            while True:
                self.eat_nl()
                t = self.peek()
                if t[0] == "SYM" and t[1] == "}":
                    self.next()
                    if pending_marks:
                        self.note(t[2], 4, "mark must precede 'variant' in splice block; skipped")
                        pending_marks = []
                    break
                if t[0] == "EOF":
                    break
                if t[0] == "MARK":
                    m = self.next()[1]
                    if m in MARKS:
                        pending_marks.append(m)
                    else:
                        wk = None
                        for k in MARKS:
                            if edit_distance(m, k) <= (1 if len(m) <= 4 else 2):
                                self.note(t[2], 3, f"wobble: '@{m}' repaired to '@{k}'")
                                wk = k
                                break
                        if wk:
                            pending_marks.append(wk)
                        else:
                            self.note(t[2], 4, f"unknown mark '@{m}' skipped")
                    continue
                if t[0] == "IDENT" and (t[1] == "variant" or edit_distance(t[1], "variant") <= 1):
                    if t[1] != "variant":
                        self.note(t[2], 3, f"wobble: '{t[1]}' repaired to 'variant'")
                    self.next()
                    vname = self.ident()
                    vmarks = pending_marks
                    pending_marks = []
                    vparams = []
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
                            pname = self.ident()
                            dflt = None
                            if self.peek() == ("SYM", "=", self.peek()[2]):
                                self.next()
                                dflt = self.expr()
                            vparams.append((pname, dflt))
                            if self.peek() == ("SYM", ",", self.peek()[2]):
                                self.next()
                            if self.pos == before:
                                self.note(t2[2], 4, "unclosed variant parameter list; auto-closed")
                                break
                    vbody = self.block()
                    vline = self.peek()[2]  # Z-CAPWINDOW: past-`}` line, mirror of parser.rs self.line() post-block
                    variants.append((vname, vparams, vbody, vmarks, vline))
                else:
                    if pending_marks:
                        self.note(t[2], 4, "mark must precede 'variant' in splice block; skipped")
                        pending_marks = []
                    self.note(t[2], 4, "unexpected token in splice block; skipped")
                    self.next()
        return ("splice", root, variants)

    def _ws_edit(self, ):
        self.next()
        target = self.ident()
        reps = []
        if self.peek() == ("SYM", "{", self.peek()[2]):
            self.next()
            while True:
                self.eat_nl()
                t = self.peek()
                if t[0] == "SYM" and t[1] == "}":
                    self.next(); break
                if t[0] == "EOF":
                    break
                if self.expect_kw("replace"):
                    frm = ""
                    if self.peek()[0] in ("STR", "INTERP"):
                        frm = self.next()[1]
                    if self.peek() == ("SYM", "->", t[2]):
                        self.next()
                    to = ""
                    if self.peek()[0] in ("STR", "INTERP"):
                        to = self.next()[1]
                    reps.append((frm, to))
                    self.end_stmt()
                else:
                    self.note(t[2], 4, "expected 'replace' in edit block; skipped")
                    self.next()
        return ("edit", target, reps)

    def _ws_ires(self, ):
        self.next()
        name = self.ident()
        self.end_stmt()
        return ("ires", name)

    def _ws_phenotype(self, ):
        self.next()
        # W01-s2 type aliases: `type Name = ann` (mirror of parser.rs).
        t = self.peek()
        t2 = self.toks[self.pos + 1] if self.pos + 1 < len(self.toks) else ("EOF", None, 0)
        if t[0] == "IDENT" and t2[0] == "SYM" and t2[1] == "=":
            alias_line = t[2]
            name = self.ident()
            self.next()  # '='
            target = self.type_ann()
            self.end_stmt()
            dup = None
            for (n, t0) in self.type_aliases:
                if n == name:
                    dup = t0
                    break
            if dup is not None:
                self.note(alias_line, 2, f"duplicate type alias '{name}'; first declaration ({ann_render(dup)}) wins")
            else:
                self.type_aliases.append((name, target))
            return ("typealias", name, target, alias_line)
        name = self.ident()
        parent = None
        if self.at_ident("from"):
            self.next()
            parent = self.ident()
        # W04: optional `implements A, B, C` (contextual word)
        implements = []
        if self.at_ident("implements"):
            self.next()
            while True:
                t = self.peek()
                if t[0] == "IDENT":
                    self.next()
                    implements.append(t[1])
                if self.peek() == ("SYM", ",", self.peek()[2]):
                    self.next()
                    continue
                break
        fields, methods = [], []
        self._ws_pheno_body(fields, methods)
        return ("pheno", Pheno(name, parent, fields, methods, implements))

    def _ws_pheno_body(self, fields, methods):
        if self.peek() == ("SYM", "{", self.peek()[2]):
            self.next()
            while True:
                self.eat_nl()
                t = self.peek()
                if t[0] == "SYM" and t[1] == "}":
                    self.next(); break
                if t[0] == "EOF":
                    self.note(t[2], 4, "phenotype body auto-closed")
                    break
                if t[0] == "MARK":
                    self.next()
                    marks = [t[1]] if t[1] in MARKS else []
                    if self.expect_kw("gene"):
                        methods.append(self.gene_def(marks)[1])
                    else:
                        self.note(t[2], 4, "mark inside phenotype must precede 'gene'; skipped")
                        self.skip_line()
                    continue
                if t[0] == "IDENT" and (t[1] == "gene" or SYNONYMS.get(t[1]) == "gene"):
                    if t[1] != "gene":
                        self.note(t[2], 2, f"synonym '{t[1]}' repaired to 'gene'")
                    self.next()
                    methods.append(self.gene_def([])[1])
                    continue
                if t[0] == "IDENT" and (t[1] == "let" or SYNONYMS.get(t[1]) == "let"):
                    if t[1] != "let":
                        self.note(t[2], 2, f"synonym '{t[1]}' repaired to 'let'")
                    self.next()
                    fname = self.ident()
                    dflt = ("null",)
                    if self.peek() == ("SYM", "=", self.peek()[2]):
                        self.next()
                        dflt = self.expr()
                    self.end_stmt()
                    if fname != "?":
                        fields.append((fname, dflt))
                    continue
                self.note(t[2], 4, "unexpected token in phenotype body; skipped")
                before = self.pos
                self.next()
                if self.pos == before:
                    break


    def _ws_sequence(self, ):
        self.next()
        g = self.gene_def([])
        if g[0] == "gene":
            g[1].seq = True
        return ("expr", ("null",)) if g[0] != "gene" else ("gene", g[1])

    def _ws_yield(self, ):
        self.next()
        t = self.peek()
        e = None
        if not (t[0] in ("NL", "EOF") or (t[0] == "SYM" and t[1] in (";", "}"))):
            e = self.expr()
        self.end_stmt()
        return ("yield", e)

    def _ws_is_def(self, word):
        # dx-r3 mirror (#59 note-parity family): bare `main { }` is the
        # community's most common top-level form and the formatter's own
        # output style — canonical sugar (rung 1 info), NOT a repair.
        # Other bare-name blocks stay rung 4 (E2017). Byte-mirrors
        # src/parser.rs's special case; without it every bare-main
        # program's stderr diverged ([info] vs [fallback E2017]).
        if word == "main":
            self.note(self.peek()[2], 1, "bare 'main' block accepted as the entry gene (canonical form: gene main())")
        else:
            self.note(self.peek()[2], 4, f"bare name block '{word}' treated as gene definition")
        gline = self.peek()[2]  # Z-CAPWINDOW: def line (name token, A13 mirror)
        self.next()  # consume the name
        params = []
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
                dflt = None
                if self.peek() == ("SYM", "=", self.peek()[2]):
                    self.next()
                    dflt = self.expr()
                params.append((pname, dflt))
                if self.peek() == ("SYM", ",", self.peek()[2]):
                    self.next()
                if self.pos == before:
                    self.note(t[2], 4, "unclosed parameter list; auto-closed")
                    break
        g = Gene(word, params, None, self.block(), line=gline)
        return ("gene", g)

