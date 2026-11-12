"""
Functions on lists — what a fanning-out path (``inventory[*].weight``) yields —
and the list literal ``[a, b]``. Lists are never null; ``sum`` / ``count`` of the
empty list is 0, ``first`` / ``min`` / ``max`` of it are null (concept §4.6).
"""
from datatype.Datatype import Datatype, common_type
from datatype.Operation import Operation


def _list_of(datatype: Datatype) -> Datatype:
    return Datatype.get(f"list<{datatype.name()}>")


def _element(types) -> Datatype | None:
    """The element type of a single ``list<T>`` argument, else ``None``."""
    if len(types) == 1 and types[0].kind() == "list":
        return types[0].element
    return None


class ListOperation(Operation):
    """``[a, b, ...]``"""

    def name(self) -> str:
        return "list"

    def generic(self, types):
        """(T, T, ...) -> list<T>"""
        common = common_type(*types)
        if not types or common is None:
            return None
        return self.overload(types, _list_of(common), lambda *values: list(values))

    def describe(self, args):
        return f"[{', '.join(arg.describe() for arg in args)}]"


class InOperation(Operation):
    """``x in list``"""

    symbol = "in"
    precedence = 5

    def name(self) -> str:
        return "in"

    def generic(self, types):
        """(T, list<T>) -> bool"""
        if len(types) != 2 or types[1].kind() != "list" or common_type(types[0], types[1].element) is None:
            return None
        return self.overload(types, Datatype.get("bool"), lambda value, values: value in values)


class SumOperation(Operation):
    def name(self) -> str:
        return "sum"

    def generic(self, types):
        """(list<int>) -> int, (list<number>) -> number"""
        element = _element(types)
        if element is None or not (element.kind() == "number" or element.widens_to("number")):
            return None
        return self.overload(types, element, lambda values: sum(v for v in values if v is not None))


class CountOperation(Operation):
    def name(self) -> str:
        return "count"

    def generic(self, types):
        """(list<T>) -> int"""
        if _element(types) is None:
            return None
        return self.overload(types, Datatype.get("int"), len)


class FirstOperation(Operation):
    def name(self) -> str:
        return "first"

    def generic(self, types):
        """(list<T>) -> T (null when empty)"""
        element = _element(types)
        if element is None:
            return None
        return self.overload(types, element, lambda values: values[0] if values else None)


class _Extreme(Operation):
    pick = staticmethod(min)

    def generic(self, types):
        """(list<T>) -> T or (T, T, ...) -> T for every ordered T"""
        pick = type(self).pick
        element = _element(types)
        if element is not None:
            if not element.ordered:
                return None
            return self.overload(
                types, element, lambda values: pick(values, key=element.sort_key) if values else None
            )
        common = common_type(*types)
        if not types or common is None or not common.ordered:
            return None
        return self.overload(types, common, lambda *values: pick(values, key=common.sort_key))


class MinOperation(_Extreme):
    def name(self) -> str:
        return "min"


class MaxOperation(_Extreme):
    pick = staticmethod(max)

    def name(self) -> str:
        return "max"


for _operation in (ListOperation, InOperation, SumOperation, CountOperation, FirstOperation,
                   MinOperation, MaxOperation):
    Operation.register(_operation())
