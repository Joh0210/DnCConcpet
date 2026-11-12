"""
Arithmetic of the expression language: ``+`` ``-`` ``*`` ``/`` ``%`` ``^``, unary
``-``, rounding and ``clamp``. Only ``add`` and ``mul`` are effects too (they have
a ``rank``); a negative ``add`` or a fractional ``mul`` does the job of the
others (concept §4.8).
"""
import math

from engine.datatype.Datatype import common_type
from engine.errors import ExpressionError
from engine.operation.Operation import Operation, signature


class AddOperation(Operation):
    """
    Sum (``+``). On bool: "or", on text: concatenation. Also an effect: a
    negative value subtracts — effects have no ``sub`` (concept §4.8).
    """

    rank = 10
    symbol = "+"
    precedence = 6

    def name(self) -> str:
        return "add"

    @signature("int", "int", returns="int")
    def ints(self, a, b):
        return a + b

    @signature("number", "number", returns="number")
    def numbers(self, a, b):
        return a + b

    @signature("bool", "bool", returns="bool")
    def bools(self, a, b):
        return a or b

    @signature("text", "text", returns="text")
    def texts(self, a, b):
        return a + b


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


class MulOperation(Operation):
    """
    Product (``*``). On bool: "and". ``int * number`` is a ``number``; as an
    effect on an ``int`` prop the result is floored when it is assigned, so a
    fractional factor rounds down (there is no ``div`` effect).
    """

    rank = 20
    symbol = "*"
    precedence = 7

    def name(self) -> str:
        return "mul"

    @signature("int", "int", returns="int")
    def ints(self, a, b):
        return a * b

    @signature("number", "number", returns="number")
    def numbers(self, a, b):
        return a * b

    @signature("bool", "bool", returns="bool")
    def bools(self, a, b):
        return a and b


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
    """Power (``^``) — a ``number``, like ``/``. Right-associative: ``2 ^ 3 ^ 2`` is ``2 ^ (3 ^ 2)``."""

    symbol = "^"
    precedence = 9
    associativity = "right"

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


class AbsOperation(Operation):
    """The amount without its sign: ``abs(-3)`` → ``3``."""

    def name(self) -> str:
        return "abs"

    @signature("int", returns="int")
    def of_int(self, a):
        return abs(a)

    @signature("number", returns="number")
    def of_number(self, a):
        return abs(a)


class ClampOperation(Operation):
    """
    ``clamp(x, min, max)``: ``x`` moved into ``[min, max]``; a null bound is open
    (``clamp(hp, 0, null)``). Works on every ordered type, enums included.
    """

    def name(self) -> str:
        return "clamp"

    def generic(self, types):
        """(T, T, T) -> T for every ordered T"""
        common = common_type(*types)
        if len(types) != 3 or common is None or not common.ordered:
            return None
        return self.overload(types, common, common.clamp)


for _operation in (AddOperation, SubOperation, MulOperation, DivOperation, ModOperation, PowOperation, NegOperation,
                   FloorOperation, CeilOperation, RoundOperation, AbsOperation, ClampOperation):
    Operation.register(_operation())
