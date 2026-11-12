from datatype.Operation import Operation, signature


class AddOperation(Operation):
    """
    Sum (``+``). On bool: "or", on text: concatenation. Also an effect: a
    negative value subtracts — effects have no ``sub`` (concept §4.8).
    """

    rank = 10
    symbol = "+"
    precedence = 6

    def name(self) -> str:
        return "add"

    @signature("int", "int", returns="int")
    def ints(self, a, b):
        return a + b

    @signature("number", "number", returns="number")
    def numbers(self, a, b):
        return a + b

    @signature("bool", "bool", returns="bool")
    def bools(self, a, b):
        return a or b

    @signature("text", "text", returns="text")
    def texts(self, a, b):
        return a + b


Operation.register(AddOperation())
