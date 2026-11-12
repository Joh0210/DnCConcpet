from datatype.Operation import Operation, signature


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


Operation.register(MulOperation())
