"""Text: templates (``"Your {stat} increases by {2 * level + 1}"``, concept §4.7)."""
from datatype.Datatype import Datatype
from datatype.Operation import Operation


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
        writers = [str if t.kind() == "text" else t.serialize for t in types]

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


Operation.register(ConcatOperation())
