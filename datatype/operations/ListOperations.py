"""
Functions on lists — what a fanning-out path (``inventory[*].weight``) yields —
and the list literal ``[a, b]``. A list is *one* value of type ``list<T>``, so
these functions take it as a single argument: the average of all attributes is
``avg(entity.attributes[*].value)``.

Lists are never null (concept §4.6). Of the empty list ``sum`` / ``count`` are 0,
``any`` is false, ``all`` is true, and ``first`` / ``last`` / ``min`` / ``max`` /
``avg`` are null.
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


class AvgOperation(Operation):
    """
    The mean of numbers — always a ``number``. (Once ``Dice`` exists, ``avg(dice)``
    — its expected value, concept §4.7 — is one more ``@signature`` here.)
    """

    def name(self) -> str:
        return "avg"

    def generic(self, types):
        """(list<int>) -> number, (list<number>) -> number"""
        element = _element(types)
        if element is None or not (element.kind() == "number" or element.widens_to("number")):
            return None

        def avg(values):
            present = [value for value in values if value is not None]
            return sum(present) / len(present) if present else None

        return self.overload(types, Datatype.get("number"), avg)


class LastOperation(Operation):
    def name(self) -> str:
        return "last"

    def generic(self, types):
        """(list<T>) -> T (null when empty)"""
        element = _element(types)
        if element is None:
            return None
        return self.overload(types, element, lambda values: values[-1] if values else None)


class _Quantifier(Operation):
    """``any`` / ``all`` over a list of bools — usually a path that fans out."""

    test = staticmethod(any)

    def generic(self, types):
        """(list<bool>) -> bool"""
        element = _element(types)
        if element is None or element.kind() != "bool":
            return None
        return self.overload(types, Datatype.get("bool"), lambda values: type(self).test(bool(v) for v in values))


class AnyOperation(_Quantifier):
    """At least one entry is true: ``any(entity.conditions[*].magic)``. False for the empty list."""

    def name(self) -> str:
        return "any"


class AllOperation(_Quantifier):
    """Every entry is true. True for the empty list."""

    test = staticmethod(all)

    def name(self) -> str:
        return "all"


for _operation in (ListOperation, InOperation, SumOperation, CountOperation, FirstOperation, LastOperation,
                   MinOperation, MaxOperation, AvgOperation, AnyOperation, AllOperation):
    Operation.register(_operation())
