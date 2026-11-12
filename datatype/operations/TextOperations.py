"""
Text: templates (``"Your {stat} increases by {2 * level + 1}"``, concept §4.7) and
helpers that write values the way a sheet shows them (``roman``, ``signed``, ``join``).
"""
from datatype.Datatype import Datatype
from datatype.Operation import Operation, signature
from errors import ExpressionError

_ROMAN = (
    (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
    (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
)


def _writer(datatype: Datatype):
    """How a value of ``datatype`` is written into a text: text as is, anything else by ``serialize``."""
    return str if datatype.kind() == "text" else datatype.serialize


def _number_text(value) -> str:
    """``2.0`` as ``2``, ``2.5`` as ``2.5``."""
    return str(int(value)) if float(value).is_integer() else str(value)


class ConcatOperation(Operation):
    """
    A template: every argument as text, joined. The parser turns
    ``"+{level} damage"`` into ``concat("+", level, " damage")``; values are
    written by their type's ``serialize``, null as nothing.
    """

    def name(self) -> str:
        return "concat"

    def generic(self, types):
        """(any, ...) -> text"""
        writers = [_writer(t) for t in types]

        def concat(*values):
            return "".join("" if value is None else write(value) for write, value in zip(writers, values))

        return self.overload(types, Datatype.get("text"), concat)

    def describe(self, args):
        parts = []
        for arg in args:
            if arg.is_literal and arg.type.kind() == "text":
                parts.append(str(arg.value))
            else:
                parts.append("{" + arg.describe() + "}")
        return '"' + "".join(parts) + '"'


class RomanOperation(Operation):
    """``roman(4)`` → ``"IV"`` — for names like ``"Shadow {roman(level)}"``. Defined for 1 … 3999."""

    def name(self) -> str:
        return "roman"

    @signature("int", returns="text")
    def of_int(self, value):
        if not 1 <= value <= 3999:
            raise ExpressionError(f"roman numerals exist for 1 … 3999, got {value}")
        digits = []
        for amount, numeral in _ROMAN:
            count, value = divmod(value, amount)
            digits.append(numeral * count)
        return "".join(digits)


class SignedOperation(Operation):
    """
    A modifier as a sheet shows it: always with its sign — ``signed(2)`` → ``"+2"``,
    ``signed(0)`` → ``"+0"``, ``signed(-1)`` → ``"-1"``.
    """

    def name(self) -> str:
        return "signed"

    @signature("int", returns="text")
    def of_int(self, value):
        return f"{value:+d}"

    @signature("number", returns="text")
    def of_number(self, value):
        text = _number_text(value)
        return text if value < 0 else f"+{text}"


class JoinOperation(Operation):
    """
    The entries of a list as one text, separated by ``separator`` (default ``", "``):
    ``"Resistant to {join(resistances, ' and ')}"``. Null entries are left out.
    """

    def name(self) -> str:
        return "join"

    def generic(self, types):
        """(list<T>) -> text, (list<T>, text) -> text"""
        if not 1 <= len(types) <= 2 or types[0].kind() != "list":
            return None
        if len(types) == 2 and types[1].kind() != "text":
            return None
        write = _writer(types[0].element)

        def join(values, separator=", "):
            return separator.join(write(value) for value in values if value is not None)

        return self.overload(types, Datatype.get("text"), join)


for _operation in (ConcatOperation, RomanOperation, SignedOperation, JoinOperation):
    Operation.register(_operation())
