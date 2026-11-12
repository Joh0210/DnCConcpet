from datatype.Datatype import common_type
from datatype.Operation import Operation


class AtLeastOperation(Operation):
    """The larger value — a lower bound. Works on every ordered type via ``sort_key``."""

    rank = 30

    def name(self) -> str:
        return "atLeast"

    def generic(self, types):
        """(T, T) -> T for every ordered T"""
        common = common_type(*types)
        if len(types) != 2 or common is None or not common.ordered:
            return None
        return self.overload(types, common, lambda previous, value: max(previous, value, key=common.sort_key))


Operation.register(AtLeastOperation())
