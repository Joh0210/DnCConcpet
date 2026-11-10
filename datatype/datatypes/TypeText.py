from datatype.Datatype import Datatype


class TypeText(Datatype):
    """Free text. Not ordered: ``range`` and ``atLeast`` are rejected for it."""

    def name(self) -> str:
        return "text"

    def deserialize(self, string):
        return string

    def serialize(self, value):
        return value

    def validate(self, value):
        if not isinstance(value, str):
            raise ValueError(f"expected text, got {value!r}")
        return value


Datatype.register(TypeText())
