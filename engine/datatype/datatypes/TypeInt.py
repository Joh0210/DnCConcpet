import math

from engine.datatype.Datatype import Datatype


class TypeInt(Datatype):
    """
    Whole numbers. A float with an integral value is accepted (``4.0`` -> ``4``)
    so arithmetic results stay usable; anything else is rejected — rounding has
    to be explicit (``floor``), otherwise type errors would hide.

    ``int`` widens to ``number``: ``2.5 * level`` is a ``number``. The one lossy
    way back is an effect on an ``int`` prop (narrowing): ``mul: 0.5`` floors.
    """

    ordered = True

    def name(self) -> str:
        return "int"

    def deserialize(self, string):
        return int(string.strip())

    def serialize(self, value):
        return str(value)

    def validate(self, value):
        if isinstance(value, bool):
            raise ValueError(f"expected int, got bool {value!r}")
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        raise ValueError(f"expected int, got {value!r}")

    def widens_to(self, kind):
        return kind == "number"

    def converter(self, source, narrowing=False):
        if narrowing and source.kind() == "number":
            return math.floor
        return super().converter(source, narrowing)


Datatype.register(TypeInt())
