from datatype.Operation import MultipleOperation, Operation


class AtMostOperation(MultipleOperation):
    """The smallest value — an upper bound. Works on every ordered type via ``sort_key``."""

    rank = 40

    def name(self) -> str:
        return "atMost"

    def use_any(self, datatype, *values):
        return min(values, key=datatype.sort_key)


Operation.register(AtMostOperation())
