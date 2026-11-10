from datatype.Operation import MultipleOperation, Operation


class AddOperation(MultipleOperation):
    """Sum. On bool: "or". A negative value subtracts — there is no ``sub``."""

    rank = 10

    def name(self) -> str:
        return "add"

    def use_int(self, *values):
        return sum(values)

    def use_number(self, *values):
        return sum(values)

    def use_bool(self, *values):
        return any(values)


Operation.register(AddOperation())
