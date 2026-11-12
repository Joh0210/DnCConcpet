"""
Operations that exist for effects (concept §4.8): each one combines the target's
value so far with the effect's value. ``add`` and ``mul`` are effects too, but
live with the arithmetic in ``ArithmeticOperations``.
"""
from datatype.Datatype import common_type
from operation.Operation import Operation


class TransformOperation(Operation):
    """
    Any function of ``previous``. The effect's value expression already computed
    the new value from ``previous`` (a path ``{"path": [], "from": "previous"}``),
    so this only takes it over. Ranked first: it rewrites the value before
    anything is added.
    """

    rank = 0

    def name(self) -> str:
        return "transform"

    def generic(self, types):
        """(T, U) -> U for every T, U"""
        if len(types) != 2:
            return None
        return self.overload(types, types[1], lambda previous, value: value)


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


class AtMostOperation(Operation):
    """The smaller value — an upper bound. Works on every ordered type via ``sort_key``."""

    rank = 40

    def name(self) -> str:
        return "atMost"

    def generic(self, types):
        """(T, T) -> T for every ordered T"""
        common = common_type(*types)
        if len(types) != 2 or common is None or not common.ordered:
            return None
        return self.overload(types, common, lambda previous, value: min(previous, value, key=common.sort_key))


class OverrideOperation(Operation):
    """Replaces the value. Ranked last so an override really wins within its priority."""

    rank = 50

    def name(self) -> str:
        return "override"

    def generic(self, types):
        """(T, U) -> U for every T, U"""
        if len(types) != 2:
            return None
        return self.overload(types, types[1], lambda previous, value: value)


for _operation in (TransformOperation, AtLeastOperation, AtMostOperation, OverrideOperation):
    Operation.register(_operation())
