"""
Comparisons (``==`` ``!=`` ``<`` ``<=`` ``>`` ``>=``). All generic: equality works
on any two types that have a common type (``null`` fits every type, so
``material != null`` works), order comparisons on every ordered type via its
``sort_key`` — enums compare by the order of their options.
"""
import operator

from datatype.Datatype import Datatype, common_type
from datatype.Operation import Operation


class _Equality(Operation):
    precedence = 5
    compare = staticmethod(operator.eq)

    def generic(self, types):
        """(T, T) -> bool for every T (null fits every T)"""
        if len(types) != 2 or common_type(*types) is None:
            return None
        return self.overload(types, Datatype.get("bool"), type(self).compare)


class EqOperation(_Equality):
    symbol = "=="

    def name(self) -> str:
        return "eq"


class NeOperation(_Equality):
    symbol = "!="
    compare = staticmethod(operator.ne)

    def name(self) -> str:
        return "ne"


class _Order(Operation):
    precedence = 5
    compare = staticmethod(operator.lt)

    def generic(self, types):
        """(T, T) -> bool for every ordered T"""
        common = common_type(*types)
        if len(types) != 2 or common is None or not common.ordered:
            return None
        key, compare = common.sort_key, type(self).compare
        return self.overload(types, Datatype.get("bool"), lambda a, b: compare(key(a), key(b)))


class LtOperation(_Order):
    symbol = "<"

    def name(self) -> str:
        return "lt"


class LeOperation(_Order):
    symbol = "<="
    compare = staticmethod(operator.le)

    def name(self) -> str:
        return "le"


class GtOperation(_Order):
    symbol = ">"
    compare = staticmethod(operator.gt)

    def name(self) -> str:
        return "gt"


class GeOperation(_Order):
    symbol = ">="
    compare = staticmethod(operator.ge)

    def name(self) -> str:
        return "ge"


for _operation in (EqOperation, NeOperation, LtOperation, LeOperation, GtOperation, GeOperation):
    Operation.register(_operation())
