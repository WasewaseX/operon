"""operon oracle: parser.__init__ (split of bootstrap/oracle.py)."""

from ..lexer import lex


from .core import PCore
from .stmt import PStmt
from .word import PWord
from .expr import PExpr
from .atom import PAtom
from .pat import PPat


class P(PCore, PStmt, PWord, PExpr, PAtom, PPat):
    pass



def parse(src):
    toks, notes = lex(src)
    p = P(toks, notes)
    stmts = p.program()
    # W24: pub-marked top-level names ride out for strict-mode export filter
    return stmts, p.notes, p.pub_names
