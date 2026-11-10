from datatype.Datatype import Datatype


class TypeInt(Datatype):
    """
    Whole numbers. A float with an integral value is accepted (``4.0`` -> ``4``)
    so arithmetic results stay usable; anything else is rejected — rounding has
    to be explicit (``floor``), otherwise type errors would hide.
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


Datatype.register(TypeInt())
