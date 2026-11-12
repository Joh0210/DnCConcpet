from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, ClassVar

from engine.errors import DefinitionError, did_you_mean


def _identity(value: Any) -> Any:
    return value


class Datatype(ABC):
    """
    Describes one value type: how a value is parsed from the definition JSON and
    from a save, how it is serialized, how values are ordered (for ``range``,
    ``clamp``, ``atLeast`` / ``atMost``) and which other types it converts to.

    There is one shared instance per type, looked up by name with :meth:`get` —
    the JSON references types only by name (``type: int``). A new type is one
    module in ``datatype/datatypes`` that calls :meth:`register`; no operation and
    no property has to change: generic operations (``==``, ``atLeast``,
    ``override``, ``? :``) work on it right away, typed ones raise a clear error
    until they get an overload for it (see :class:`engine.operation.Operation.Operation`).

    Parametrized types (``list<number>``, ``ref<weapon>``) are created on first
    use by a registered constructor (:meth:`register_constructor`) and then
    shared like every other type.

    Types are static: every expression node knows its type when the definition
    loads, so operations are resolved once, not on every evaluation.
    """

    _registry: ClassVar[dict[str, Datatype]] = {}
    _constructors: ClassVar[dict[str, Callable[[Datatype], Datatype]]] = {}

    #: Whether values have an order, so ``range``, ``clamp`` and ``atLeast`` make sense.
    ordered: ClassVar[bool] = False

    # ------------------------------------------------------------------ registry

    @staticmethod
    def register(datatype: Datatype) -> Datatype:
        """Make ``datatype`` available under its :meth:`name`. Returns it for chaining."""
        name = datatype.name()
        if name in Datatype._registry:
            raise DefinitionError(f"datatype '{name}' is registered twice")
        Datatype._registry[name] = datatype
        return datatype

    @staticmethod
    def register_constructor(base: str, constructor: Callable[[Datatype], Datatype]) -> None:
        """Make ``base<T>`` available: ``constructor(T)`` builds the type the first time it is used."""
        if base in Datatype._constructors:
            raise DefinitionError(f"type constructor '{base}' is registered twice")
        Datatype._constructors[base] = constructor

    @staticmethod
    def get(name: str) -> Datatype:
        """The datatype registered as ``name`` (``int``, ``Attribute``, ``list<number>``, ...)."""
        # Imported lazily: the type modules import this one. Importing registers them.
        import engine.datatype.datatypes  # noqa: F401

        name = name.replace(" ", "")  # "list< number >" is "list<number>"
        found = Datatype._registry.get(name)
        if found is not None:
            return found
        if name.endswith(">") and "<" in name:
            return Datatype._construct(name)
        raise DefinitionError(f"unknown datatype '{name}'{did_you_mean(name, Datatype._registry)}")

    @staticmethod
    def _construct(name: str) -> Datatype:
        """Build ``base<argument>`` with the registered constructor and register it, so it is built once."""
        base, argument = name[:-1].split("<", 1)
        try:
            constructor = Datatype._constructors[base]
        except KeyError:
            raise DefinitionError(
                f"unknown type constructor '{base}' in '{name}'{did_you_mean(base, Datatype._constructors)}"
            ) from None
        built = constructor(argument)
        Datatype._registry[name] = built
        return built

    @classmethod
    def instance(cls) -> Datatype:
        """The shared instance of a non-parametrized type (``TypeInt.instance()``)."""
        import engine.datatype.datatypes  # noqa: F401

        for registered in Datatype._registry.values():
            if type(registered) is cls:
                return registered
        raise DefinitionError(f"datatype class {cls.__name__} is not registered")

    # ------------------------------------------------------------------ identity

    @abstractmethod
    def name(self) -> str:
        """
        Returns the name of the datatype. Can be used for feedback.
        It is also the key the definition JSON uses (``type: int``).
        """

    def kind(self) -> str:
        """
        The family operation signatures match on. Equals :meth:`name` except for
        parametrized types: every kernel enum has its own name (``Attribute``,
        ``Slot``) but the shared kind ``enum``; ``list<int>`` has the kind ``list``.
        """
        return self.name()

    # ------------------------------------------------------------------ values

    @abstractmethod
    def deserialize(self, string: str) -> Any:
        """Parse a value written by :meth:`serialize` (or a string literal in the JSON)."""

    @abstractmethod
    def serialize(self, value: Any) -> str:
        """The value as the string stored in a save (also used to show it in a text)."""

    def literal(self, value: Any) -> str:
        """
        The value as a literal of the expression language (concept §4.7), for
        :meth:`InnerFunction.describe`. Usually its serialized form; a type with
        its own literal syntax overrides this (enums: ``.heavy``).
        """
        return self.serialize(value)

    @abstractmethod
    def validate(self, value: Any) -> Any:
        """
        Check a native value and return it normalized. Raises ``ValueError``
        when the value is not of this type.
        """

    def parse(self, raw: Any) -> Any:
        """
        A literal from the definition JSON or a save. A string goes through
        :meth:`deserialize` (``"10"``), anything else through :meth:`validate`
        (``10``) — the JSON may hold either.
        """
        if isinstance(raw, str):
            return self.deserialize(raw)
        return self.validate(raw)

    # ------------------------------------------------------------------ conversion

    def widens_to(self, kind: str) -> bool:
        """
        Whether every value of this type is also a valid value of the type kind
        ``kind`` (``int`` widens to ``number``). Operations use it to find an
        overload, assignments to accept a value without converting it.
        """
        return False

    def converter(self, source: Datatype, narrowing: bool = False) -> Callable[[Any], Any] | None:
        """
        How a value of type ``source`` becomes a value of this type, or ``None``
        when it cannot. Without ``narrowing`` only lossless cases pass: the same
        type, a widening (``int`` → ``number``) or ``null``. With ``narrowing``
        a type may also accept a lossy conversion — effects use it, so a
        fractional ``mul`` on an ``int`` prop floors (concept §4.8).
        """
        if source is self or source.kind() == "null" or source.widens_to(self.kind()):
            return _identity
        return None

    # ------------------------------------------------------------------ order

    def sort_key(self, value: Any) -> Any:
        """What values of this type are compared by. Only for :attr:`ordered` types."""
        if not self.ordered:
            raise ValueError(f"type '{self.name()}' has no order")
        return value

    def clamp(self, value: Any, lower: Any = None, upper: Any = None) -> Any:
        """``value`` moved into ``[lower, upper]``; ``None`` means unbounded."""
        if lower is not None and self.sort_key(value) < self.sort_key(lower):
            value = lower
        if upper is not None and self.sort_key(value) > self.sort_key(upper):
            value = upper
        return value

    def __repr__(self) -> str:
        return f"<Datatype {self.name()}>"


def common_type(*types: Datatype) -> Datatype | None:
    """
    The type all ``types`` fit into without conversion, or ``None``: the same
    type, the wider of two (``int`` + ``number`` → ``number``); ``null`` fits
    every type. Generic operations (``==``, ``atLeast``, ``? :``, ``??``) use it.
    """
    result: Datatype | None = None
    for current in types:
        if result is None or result.kind() == "null":
            result = current
        elif current is result or current.kind() == "null" or current.widens_to(result.kind()):
            continue
        elif result.widens_to(current.kind()):
            result = current
        else:
            return None
    return result
