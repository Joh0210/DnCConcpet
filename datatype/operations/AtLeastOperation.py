from datatype.Operation import MultipleOperation, Operation


class AtLeastOperation(MultipleOperation):
    """The largest value — a lower bound. Works on every ordered type via ``sort_key``."""

    rank = 30

    def name(self) -> str:
        return "atLeast"

    def use_any(self, datatype, *values):
        return max(values, key=datatype.sort_key)


Operation.register(AtLeastOperation())
