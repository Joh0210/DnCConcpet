import math

from datatype.Operation import MultipleOperation, Operation


class MulOperation(MultipleOperation):
    """
    Product. On int the result is floored, so a fractional factor rounds down
    (there is no ``div``). On bool: "and".
    """

    rank = 20

    def name(self) -> str:
        return "mul"

    def use_int(self, *values):
        # math.prod instead of operator.mul: works for any number of values.
        return math.floor(math.prod(values))

    def use_number(self, *values):
        return math.prod(values)

    def use_bool(self, *values):
        return all(values)


Operation.register(MulOperation())
