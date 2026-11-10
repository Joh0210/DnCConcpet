from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from errors import DefinitionError, UnsupportedOperationError, did_you_mean


class Operation(ABC):
    """
    How an effect combines the value so far (``previous``) with its own value
    (concept §4.8: ``add``, ``mul``, ``atLeast``, ``atMost``, ``override``,
    ``transform``).

    Dispatch: ``Datatype.use_operation(op, *values)`` calls ``op.use(datatype, *values)``,
    which picks

    1. ``use_<kind>(*values)`` if the operation implements that type
       (``use_int``, ``use_bool``, ``use_enum``, ...),
    2. else the generic ``use_any(datatype, *values)`` if the operation has one,
    3. else raises :class:`UnsupportedOperationError`.

    So a new operation implements only the types it supports, and a new datatype
    needs no change to existing operations: it gets ``use_any`` or a clear error.
    """

    _registry: ClassVar[dict[str, Operation]] = {}

    #: Position among the effects of one priority stage; lower runs first.
    #: Compute (transform, add, mul), then clamp (atLeast, atMost), then override.
    rank: ClassVar[int] = 0
    #: Number of values the operation takes; ``None`` = any number (a fold).
    arity: ClassVar[int | None] = None

    # ------------------------------------------------------------------ registry

    @staticmethod
    def register(operation: Operation) -> Operation:
        name = operation.name()
        if name in Operation._registry:
            raise DefinitionError(f"operation '{name}' is registered twice")
        Operation._registry[name] = operation
        return operation

    @staticmethod
    def get(name: str) -> Operation:
        """The operation registered as ``name`` — the key used in an effect (``add: 2``)."""
        Operation._load_builtins()
        try:
            return Operation._registry[name]
        except KeyError:
            raise DefinitionError(
                f"unknown operation '{name}'{did_you_mean(name, Operation._registry)}"
            ) from None

    @staticmethod
    def names() -> list[str]:
        Operation._load_builtins()
        return list(Operation._registry)

    @classmethod
    def instance(cls) -> Operation:
        """The shared instance of this operation (``AddOperation.instance()``)."""
        Operation._load_builtins()
        for registered in Operation._registry.values():
            if type(registered) is cls:
                return registered
        raise DefinitionError(f"operation class {cls.__name__} is not registered")

    @staticmethod
    def _load_builtins() -> None:
        import datatype.operations  # noqa: F401 — registers the built-in operations

    # ------------------------------------------------------------------ use

    @abstractmethod
    def name(self) -> str:
        """
        Returns the name of the operation. Can be used for feedback.
        It is also the key in the effect JSON (``add``, ``atLeast``).
        """

    def use(self, datatype, *values) -> Any:
        if self.arity is not None and len(values) != self.arity:
            raise TypeError(
                f"operation '{self.name()}' takes {self.arity} values, got {len(values)}"
            )

        specific = getattr(self, f"use_{datatype.kind()}", None)
        if specific is not None:
            return specific(*values)

        generic = getattr(self, "use_any", None)
        if generic is not None:
            return generic(datatype, *values)

        raise UnsupportedOperationError(
            f"operation '{self.name()}' does not support type '{datatype.name()}'"
        )

    def __repr__(self) -> str:
        return f"<Operation {self.name()}>"


class SingleOperation(Operation):
    """Takes exactly one value (unary)."""

    arity = 1


class MultipleOperation(Operation):
    """Folds any number of values: ``add(a, b, c)``. Effects call it with ``(previous, value)``."""

    arity = None


class DuoOperation(Operation):
    """Takes exactly ``(previous, value)``."""

    arity = 2
