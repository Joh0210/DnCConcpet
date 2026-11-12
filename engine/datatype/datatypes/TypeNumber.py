from engine.datatype.Datatype import Datatype


class TypeNumber(Datatype):
    """Any real number (weights, item value, multipliers). Ints stay ints."""

    ordered = True

    def name(self) -> str:
        return "number"

    def deserialize(self, string):
        number = float(string.strip())
        return int(number) if number.is_integer() else number

    def serialize(self, value):
        return str(value)

    def validate(self, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"expected number, got {value!r}")
        return value


Datatype.register(TypeNumber())
