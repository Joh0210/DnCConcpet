from datatype.Datatype import Datatype


class TypeBool(Datatype):
    """``True`` / ``False``. Ordered (``False < True``) so ``atLeast`` works as "or"."""

    ordered = True

    _TRUE = ("true", "yes", "1")
    _FALSE = ("false", "no", "0")

    def name(self) -> str:
        return "bool"

    def deserialize(self, string):
        text = string.strip().lower()
        if text in self._TRUE:
            return True
        if text in self._FALSE:
            return False
        raise ValueError(f"expected bool, got {string!r}")

    def serialize(self, value):
        return str(value)

    def literal(self, value):
        return "true" if value else "false"

    def validate(self, value):
        if isinstance(value, bool):
            return value
        raise ValueError(f"expected bool, got {value!r}")


Datatype.register(TypeBool())
