"""operon oracle: interp.__init__ (split of bootstrap/oracle.py)."""



from .core import ICore
from .pat import IPat
from .stmt import IStmt
from .eval import IEval
from .binop import IBinop
from .call import ICall
from .grn import IGrn
from .gene import IGene
from .method import IMethod
from .cycle import ICycle
from .builtin import IBuiltin
from .module import IModule


class Interp(ICore, IPat, IStmt, IEval, IBinop, ICall, IGrn, IGene, IMethod, ICycle, IBuiltin, IModule):
    pass
