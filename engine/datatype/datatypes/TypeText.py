from engine.datatype.Datatype import Datatype


class TypeText(Datatype):
    """Free text. Not ordered: ``range`` and ``atLeast`` are rejected for it."""

    def name(self) -> str:
        return "text"

    def deserialize(self, string):
        return string

    def serialize(self, value):
        return value

    def literal(self, value):
        # Single quotes, as inside templates (``"{join(list, ' and ')}"``). The concept does not fix
        # an escape syntax yet; a backslash is assumed — align with the parser once it exists.
        escaped = value.replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"

    def validate(self, value):
        if not isinstance(value, str):
            raise ValueError(f"expected text, got {value!r}")
        return value


Datatype.register(TypeText())
