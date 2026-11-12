from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Sequence

from datatype.Datatype import Datatype
from errors import DefinitionError, UnsupportedOperationError, did_you_mean

if TYPE_CHECKING:
    from InnerFunction import InnerFunction


def signature(*params: str, returns: str):
    """
    Declare a method of an :class:`Operation` as the implementation for the
    argument kinds ``params`` (``"int"``, ``"number"``, ``"enum"``, ``"list"``,
    ``"any"``), returning the type ``returns``::

        @signature("int", "int", returns="int")
        def ints(self, a, b): return a + b
    """

    def mark(method):
        method._signature = (tuple(params), returns)
        return method

    return mark


class Overload:
    """
    One resolved implementation of an operation for concrete argument types:
    what to call and which type it returns. Resolved once when an expression is
    built; evaluating then only calls :attr:`impl`.

    An eager overload is called with the argument *values*, a lazy one
    (``Operation.lazy``) with the context and the argument *nodes*.
    """

    __slots__ = ("operation", "params", "returns", "impl")

    def __init__(self, operation: Operation, params: Sequence[Datatype], returns: Datatype, impl: Callable):
        self.operation = operation
        self.params = tuple(params)
        self.returns = returns
        self.impl = impl

    def __call__(self, *args: Any) -> Any:
        return self.impl(*args)

    def __repr__(self) -> str:
        params = ", ".join(t.name() for t in self.params)
        return f"<Overload {self.operation.name()}({params}) -> {self.returns.name()}>"


class Operation(ABC):
    """
    Everything that computes a value from other values: arithmetic (``add``,
    ``div``), comparison (``lt``), logic (``and``, ``? :``), list functions
    (``sum``) — and the effect operations of concept §4.8 (``add``, ``mul``,
    ``atLeast``, ``atMost``, ``override``, ``transform``). An expression node
    (``{"op": "add", "args": [...]}``) names one by id.

    **The operation is the entry point, not the datatype.** It is called with
    any argument types and decides what it does with them, by *signature*:

    1. a method marked ``@signature(...)`` whose parameter kinds match the
       argument types exactly (``use_<kind>`` of old, generalized from one type
       to all arguments),
    2. the same with widening (``int`` fits a ``number`` parameter),
    3. :meth:`generic` — for rules over *any* type (``==``, ``atLeast`` on every
       ordered type, ``? :``); it gets the argument types and returns an
       :class:`Overload` or ``None`` (``use_any`` of old),
    4. else :class:`UnsupportedOperationError`, listing what is supported.

    The result type comes from the overload, not from the arguments:
    ``lt(int, int)`` is a ``bool``, ``div(int, int)`` a ``number``.

    Resolution happens when an expression is built (the types are static) and
    is cached per argument types, so evaluating costs one call. A new type
    needs no change here — generic operations work on it at once, typed ones
    raise a clear error until they get an overload. A new operation is a
    subclass plus :meth:`register`.

    **Lazy operations** (``and``, ``or``, ``??``, ``? :``) get the evaluation
    context and the argument *nodes* and evaluate only what they need — so
    ``entity != null and entity.level > 3`` never reads ``entity.level`` while
    there is no entity, and an untaken branch never becomes a dependency.
    """

    _registry: ClassVar[dict[str, Operation]] = {}
    #: ``(method name, (param kinds, return type name))`` of every ``@signature`` method, base first.
    _declared: ClassVar[list[tuple[str, tuple[tuple[str, ...], str]]]] = []

    #: Position among the effects of one priority stage; lower runs first.
    #: Compute (transform, add, mul), then clamp (atLeast, atMost), then override.
    #: ``None``: the operation cannot be used as an effect (``sub``, ``lt``, ...).
    rank: ClassVar[int | None] = None
    #: Gets ``(ctx, *argument nodes)`` instead of the argument values.
    lazy: ClassVar[bool] = False
    #: How the expression language writes it, for :meth:`describe`: an infix /
    #: prefix symbol, and how tightly it binds (higher = tighter; concept §4.7).
    symbol: ClassVar[str | None] = None
    precedence: ClassVar[int] = 10

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        own = [(name, member._signature) for name, member in vars(cls).items() if hasattr(member, "_signature")]
        inherited = [entry for base in cls.__bases__ for entry in getattr(base, "_declared", [])]
        cls._declared = inherited + own

    def __init__(self) -> None:
        self._resolved: dict[tuple[Datatype, ...], Overload] = {}

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
        """The operation registered as ``name`` — the id in ``{"op": ...}`` and the key of an effect (``add: 2``)."""
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

    @staticmethod
    def effect_names() -> list[str]:
        """The operations an effect may use (those with a :attr:`rank`), in effect order."""
        Operation._load_builtins()
        effects = [op for op in Operation._registry.values() if op.rank is not None]
        return [op.name() for op in sorted(effects, key=lambda op: op.rank)]

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

    # ------------------------------------------------------------------ resolution

    @abstractmethod
    def name(self) -> str:
        """
        Returns the name of the operation. Can be used for feedback.
        It is also the id in the expression JSON and the key of an effect (``add``, ``atLeast``).
        """

    def resolve(self, types: Sequence[Datatype]) -> Overload:
        """The implementation for arguments of ``types`` (cached). Raises :class:`UnsupportedOperationError`."""
        key = tuple(types)
        found = self._resolved.get(key)
        if found is None:
            found = self._resolved[key] = self._resolve(key)
        return found

    def _resolve(self, types: tuple[Datatype, ...]) -> Overload:
        for widening in (False, True):
            for method, (params, returns) in self._declared:
                if len(params) == len(types) and all(
                    _fits(arg, param, widening) for arg, param in zip(types, params)
                ):
                    return Overload(self, types, Datatype.get(returns), getattr(self, method))
        found = self.generic(types)
        if found is not None:
            return found
        raise UnsupportedOperationError(
            f"operation '{self.name()}' does not support ({', '.join(t.name() for t in types)})"
            f"{self._supported()}"
        )

    def generic(self, types: tuple[Datatype, ...]) -> Overload | None:
        """
        Fallback for argument types no ``@signature`` covers: return an
        :class:`Overload` if the operation handles ``types``, else ``None``.
        """
        return None

    def overload(self, types: Sequence[Datatype], returns: Datatype, impl: Callable) -> Overload:
        """Helper for :meth:`generic`."""
        return Overload(self, types, returns, impl)

    def _supported(self) -> str:
        shown = [f"({', '.join(params)}) -> {returns}" for _, (params, returns) in self._declared]
        if type(self).generic is not Operation.generic:
            shown.append((type(self).generic.__doc__ or "generic").strip().splitlines()[0])
        return f"; supported: {'; '.join(shown)}" if shown else ""

    # ------------------------------------------------------------------ text

    def describe(self, args: Sequence[InnerFunction]) -> str:
        """How the expression language writes this operation applied to ``args``."""
        if self.symbol is not None and len(args) == 2:
            left = _wrap(args[0], self.precedence, strict=False)
            right = _wrap(args[1], self.precedence, strict=True)
            return f"{left} {self.symbol} {right}"
        if self.symbol is not None and len(args) == 1:
            separator = " " if self.symbol[-1].isalpha() else ""
            return f"{self.symbol}{separator}{_wrap(args[0], self.precedence, strict=False)}"
        return f"{self.name()}({', '.join(arg.describe() for arg in args)})"

    def __repr__(self) -> str:
        return f"<Operation {self.name()}>"


def _fits(arg: Datatype, param: str, widening: bool) -> bool:
    if param == "any" or arg.kind() == param or arg.name() == param:
        return True
    return widening and arg.widens_to(param)


def _wrap(node: InnerFunction, precedence: int, strict: bool) -> str:
    """``node`` described, in parentheses if it binds looser than its parent (or equally, on the right)."""
    text = node.describe()
    inner = node.precedence
    if inner < precedence or (strict and inner == precedence):
        return f"({text})"
    return text
