"""
Logic: ``not``, and the *lazy* operations ``and``, ``or``, ``??`` and ``? :``.

Lazy operations get the context and their argument nodes and evaluate only what
they need. That is what makes a null check protect what follows it
(``entity != null and entity.level > 3``, concept §4.6), and it keeps the
untaken branch from becoming a dependency of the value.
"""
from datatype.Datatype import common_type
from operation.Operation import Operation, signature


class NotOperation(Operation):
    symbol = "not"
    precedence = 4

    def name(self) -> str:
        return "not"

    @signature("bool", returns="bool")
    def invert(self, a):
        return not a


class AndOperation(Operation):
    lazy = True
    symbol = "and"
    precedence = 3

    def name(self) -> str:
        return "and"

    @signature("bool", "bool", returns="bool")
    def bools(self, ctx, a, b):
        return bool(a.evaluate(ctx)) and bool(b.evaluate(ctx))


class OrOperation(Operation):
    lazy = True
    symbol = "or"
    precedence = 2

    def name(self) -> str:
        return "or"

    @signature("bool", "bool", returns="bool")
    def bools(self, ctx, a, b):
        return bool(a.evaluate(ctx)) or bool(b.evaluate(ctx))


class CoalesceOperation(Operation):
    """``a ?? b``: ``a``, or ``b`` when ``a`` is null (an absent ``?.`` path)."""

    lazy = True
    symbol = "??"
    precedence = 1
    parenthesize_when_combined = True  # `a ?? b * 2` is an error; precedence surprises are too likely

    def name(self) -> str:
        return "coalesce"

    def generic(self, types):
        """(T, T) -> T for every T"""
        common = common_type(*types)
        if len(types) != 2 or common is None:
            return None

        def coalesce(ctx, a, b):
            value = a.evaluate(ctx)
            return value if value is not None else b.evaluate(ctx)

        return self.overload(types, common, coalesce)


class CondOperation(Operation):
    """``condition ? a : b`` — only the taken branch is evaluated."""

    lazy = True
    precedence = 0

    def name(self) -> str:
        return "cond"

    def generic(self, types):
        """(bool, T, T) -> T for every T"""
        if len(types) != 3 or types[0].kind() != "bool":
            return None
        common = common_type(types[1], types[2])
        if common is None:
            return None
        return self.overload(
            types, common,
            lambda ctx, condition, a, b: a.evaluate(ctx) if condition.evaluate(ctx) else b.evaluate(ctx),
        )

    def describe(self, args):
        parts = [self._operand(arg, strict=True) for arg in args]
        return f"{parts[0]} ? {parts[1]} : {parts[2]}"


for _operation in (NotOperation, AndOperation, OrOperation, CoalesceOperation, CondOperation):
    Operation.register(_operation())
