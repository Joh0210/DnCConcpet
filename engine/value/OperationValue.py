from __future__ import annotations

from typing import Any, Callable

from engine.errors import DefinitionError, ExpressionError
from engine.operation.Operation import Operation
from engine.value.InnerFunction import EvalContext, InnerFunction


class OperationValue(InnerFunction):
    """
    An operation applied to argument values: ``{"op": "<id>", "args": [VALUE, ...]}``.

    Building it resolves the operation for the arguments' static types
    (:meth:`Operation.resolve`) — that picks the implementation *and* the result
    type (``lt(int, int)`` → ``bool``). A type error therefore stops the
    definition from loading instead of a running game. Evaluating is one call:

    - eager operations get the argument values (evaluated first),
    - lazy operations (``and``, ``or``, ``??``, ``? :``) get the context and the
      argument nodes and evaluate only what they need.
    """

    KEYS = {"op", "args"}

    def __init__(self, operation: Operation, args: list[InnerFunction]):
        self.operation = operation
        self.args = tuple(args)
        missing = [arg.describe() for arg in self.args if arg.type is None]
        if missing:
            raise DefinitionError(f"'{missing[0]}' has no type, so '{operation.name()}' cannot use it")
        overload = operation.resolve([arg.type for arg in self.args])
        self.type = overload.returns
        self._impl: Callable[..., Any] = overload.impl
        self._lazy = operation.lazy
        self.precedence = operation.precedence

    @classmethod
    def from_json(cls, raw: dict, build: Callable[[Any], InnerFunction]) -> OperationValue:
        args = raw.get("args", [])
        if not isinstance(args, list):
            raise DefinitionError(f"'args' of operation '{raw['op']}' must be a list, got {args!r}")
        return cls(Operation.get(raw["op"]), [build(arg) for arg in args])

    def evaluate(self, ctx: EvalContext) -> Any:
        try:
            if self._lazy:
                return self._impl(ctx, *self.args)
            return self._impl(*[arg.evaluate(ctx) for arg in self.args])
        except (TypeError, ArithmeticError) as error:
            # e.g. a null where the operation needs a value: the content forgot a `??`
            raise ExpressionError(f"'{self.describe()}' failed: {error}") from error

    def describe(self) -> str:
        return self.operation.describe(self.args)

    def __repr__(self) -> str:
        return f"<OperationValue {self.describe()}: {self.type.name()}>"
