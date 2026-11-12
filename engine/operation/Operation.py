from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Sequence

from engine.datatype.Datatype import Datatype
from engine.errors import DefinitionError, UnsupportedOperationError, did_you_mean

if TYPE_CHECKING:
    from engine.value.InnerFunction import InnerFunction


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

    **Design decision: the operation is the entry point, not the datatype.** It
    is called with any argument types and decides what it does with them, by
    *signature* — on all argument types, not only on the first one's datatype:

    1. a method marked ``@signature(...)`` whose parameter kinds match the
       argument types exactly,
    2. the same with widening (``int`` fits a ``number`` parameter),
    3. :meth:`generic` — for rules over *any* type (``==``, ``atLeast`` on every
       ordered type, ``? :``); it gets the argument types and returns an
       :class:`Overload` or ``None``,
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
    _signatures: ClassVar[list[tuple[str, tuple[tuple[str, ...], str]]]] = []

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
    #: Which side of an infix operator may hold the same precedence without
    #: parentheses: ``"left"`` (``a - b - c``), ``"right"`` (``^``) or ``"none"``
    #: (comparisons — ``a == b == c`` has no meaning, both sides are parenthesized).
    associativity: ClassVar[str] = "left"
    #: Combined with another operator, it must be parenthesized on both sides (``??``, concept §4.7).
    parenthesize_when_combined: ClassVar[bool] = False

    def __init_subclass__(cls, **kwargs):
        # Collect the @signature methods once per class: inherited ones first, so a
        # subclass extends its base's overloads; the order is the order of resolution.
        super().__init_subclass__(**kwargs)
        own = [(name, member._signature) for name, member in vars(cls).items() if hasattr(member, "_signature")]
        inherited = [entry for base in cls.__bases__ for entry in getattr(base, "_signatures", [])]
        cls._signatures = inherited + own

    def __init__(self) -> None:
        self._resolved: dict[tuple[Datatype, ...], Overload] = {}

    # ------------------------------------------------------------------ registry

    @staticmethod
    def register(operation: Operation) -> Operation:
        """Make ``operation`` available under its :meth:`name`. Returns it for chaining."""
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
        """Every registered operation id."""
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
        # Imported lazily: the operation modules import this one. Importing registers them.
        import engine.operation.operations  # noqa: F401

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
        # Exact matches win over widened ones: (int, int) picks the int overload, not the number one.
        for widening in (False, True):
            for method, (params, returns) in self._signatures:
                if len(params) == len(types) and all(
                    _matches(arg, param, widening) for arg, param in zip(types, params)
                ):
                    return Overload(self, types, Datatype.get(returns), getattr(self, method))
        found = self.generic(types)
        if found is not None:
            return found
        raise UnsupportedOperationError(
            f"operation '{self.name()}' does not support ({', '.join(t.name() for t in types)})"
            f"{self._describe_supported()}"
        )

    def generic(self, types: tuple[Datatype, ...]) -> Overload | None:
        """
        Fallback for argument types no ``@signature`` covers: return an
        :class:`Overload` if the operation handles ``types``, else ``None``.

        The first line of an override's docstring is part of the error message
        that lists what an operation supports — keep it a signature like
        ``(T, T) -> T for every ordered T``.
        """
        return None

    def overload(self, types: Sequence[Datatype], returns: Datatype, impl: Callable) -> Overload:
        """Helper for :meth:`generic`."""
        return Overload(self, types, returns, impl)

    def _describe_supported(self) -> str:
        """``; supported: (int, int) -> int; ...`` for error messages, or an empty string."""
        shown = [f"({', '.join(params)}) -> {returns}" for _, (params, returns) in self._signatures]
        if type(self).generic is not Operation.generic:
            shown.append((type(self).generic.__doc__ or "generic").strip().splitlines()[0])
        return f"; supported: {'; '.join(shown)}" if shown else ""

    # ------------------------------------------------------------------ text

    def describe(self, args: Sequence[InnerFunction]) -> str:
        """How the expression language writes this operation applied to ``args``."""
        if self.symbol is not None and len(args) == 2:
            left = self._operand(args[0], strict=self.associativity != "left")
            right = self._operand(args[1], strict=self.associativity != "right")
            return f"{left} {self.symbol} {right}"
        if self.symbol is not None and len(args) == 1:
            separator = " " if self.symbol[-1].isalpha() else ""
            return f"{self.symbol}{separator}{self._operand(args[0], strict=False)}"
        return f"{self.name()}({', '.join(arg.describe() for arg in args)})"

    def _operand(self, node: InnerFunction, strict: bool) -> str:
        """
        ``node`` described as an operand of this operator, in parentheses where
        concept §4.7 requires them: when it binds looser than this operator (or
        equally, if ``strict``), or when one of the two is ``??`` and the other
        is a different operator.
        """
        text = node.describe()
        inner = node.precedence
        if inner < self.precedence or (strict and inner == self.precedence):
            return f"({text})"
        child = getattr(node, "operation", None)  # only operation nodes have one
        is_operator = inner < Operation.precedence  # atoms and calls bind tightest
        if is_operator and child is not self and (
            self.parenthesize_when_combined or (child is not None and child.parenthesize_when_combined)
        ):
            return f"({text})"
        return text

    def __repr__(self) -> str:
        return f"<Operation {self.name()}>"


def _matches(arg: Datatype, param: str, widening: bool) -> bool:
    """Whether an argument of type ``arg`` fits a ``@signature`` parameter (a kind, a type name or ``any``)."""
    if param == "any" or arg.kind() == param or arg.name() == param:
        return True
    return widening and arg.widens_to(param)

