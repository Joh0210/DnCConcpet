"""
Arithmetic of the expression language besides ``add`` / ``mul`` (which are also
effects): ``-`` ``/`` ``%`` ``^``, unary ``-``, and rounding. None of these is an
effect — a negative ``add`` or a fractional ``mul`` does that job (concept §4.8).
"""
import math

from datatype.Operation import Operation, signature
from errors import ExpressionError


class SubOperation(Operation):
    """Difference (``-``)."""

    symbol = "-"
    precedence = 6

    def name(self) -> str:
        return "sub"

    @signature("int", "int", returns="int")
    def ints(self, a, b):
        return a - b

    @signature("number", "number", returns="number")
    def numbers(self, a, b):
        return a - b


class DivOperation(Operation):
    """Division (``/``) — always a ``number``; ``floor`` / ``ceil`` / ``round`` make it whole."""

    symbol = "/"
    precedence = 7

    def name(self) -> str:
        return "div"

    @signature("number", "number", returns="number")
    def numbers(self, a, b):
        if b == 0:
            raise ExpressionError("division by zero")
        return a / b


class ModOperation(Operation):
    """Remainder (``%``)."""

    symbol = "%"
    precedence = 7

    def name(self) -> str:
        return "mod"

    @signature("int", "int", returns="int")
    def ints(self, a, b):
        if b == 0:
            raise ExpressionError("modulo by zero")
        return a % b

    @signature("number", "number", returns="number")
    def numbers(self, a, b):
        if b == 0:
            raise ExpressionError("modulo by zero")
        return a % b


class PowOperation(Operation):
    """Power (``^``) — a ``number``, like ``/``."""

    symbol = "^"
    precedence = 9

    def name(self) -> str:
        return "pow"

    @signature("number", "number", returns="number")
    def numbers(self, a, b):
        return a ** b


class NegOperation(Operation):
    """Unary minus (``-x``)."""

    symbol = "-"
    precedence = 8

    def name(self) -> str:
        return "neg"

    @signature("int", returns="int")
    def of_int(self, a):
        return -a

    @signature("number", returns="number")
    def of_number(self, a):
        return -a


class FloorOperation(Operation):
    """Round down to an ``int`` — the explicit conversion ``number`` → ``int``."""

    def name(self) -> str:
        return "floor"

    @signature("number", returns="int")
    def number(self, a):
        return math.floor(a)


class CeilOperation(Operation):
    """Round up to an ``int``."""

    def name(self) -> str:
        return "ceil"

    @signature("number", returns="int")
    def number(self, a):
        return math.ceil(a)


class RoundOperation(Operation):
    """Round to the nearest ``int``; halves go away from zero, as players expect."""

    def name(self) -> str:
        return "round"

    @signature("number", returns="int")
    def number(self, a):
        return math.floor(a + 0.5) if a >= 0 else -math.floor(-a + 0.5)


for _operation in (SubOperation, DivOperation, ModOperation, PowOperation, NegOperation,
                   FloorOperation, CeilOperation, RoundOperation):
    Operation.register(_operation())
