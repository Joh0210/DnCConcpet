from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from errors import DefinitionError, did_you_mean


class Datatype(ABC):
    """
    Describes one value type: how a value is parsed from the definition JSON and
    from a save, how it is serialized, how values are ordered (for ``range``,
    ``clamp``, ``atLeast`` / ``atMost``) and which operations it supports.

    There is one shared instance per type, looked up by name with :meth:`get` —
    the JSON references types only by name (``type: int``). A new type is one
    module in ``datatype/datatypes`` that calls :meth:`register`; no operation and
    no property has to change (see :meth:`Operation.use` for the dispatch).
    """

    _registry: ClassVar[dict[str, Datatype]] = {}

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
    def get(name: str) -> Datatype:
        """The datatype registered as ``name`` (``int``, ``Attribute``, ...)."""
        import datatype.datatypes  # noqa: F401 — registers the built-in types on first use

        try:
            return Datatype._registry[name]
        except KeyError:
            raise DefinitionError(
                f"unknown datatype '{name}'{did_you_mean(name, Datatype._registry)}"
            ) from None

    @classmethod
    def instance(cls) -> Datatype:
        """The shared instance of a non-parametrized type (``TypeInt.instance()``)."""
        import datatype.datatypes  # noqa: F401

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
        The family operations dispatch on (``use_<kind>``). Equals :meth:`name`
        except for parametrized types: every kernel enum has its own name
        (``Attribute``, ``Slot``) but the shared kind ``enum``.
        """
        return self.name()

    # ------------------------------------------------------------------ values

    @abstractmethod
    def deserialize(self, string: str) -> Any:
        """Parse a value written by :meth:`serialize` (or a string literal in the JSON)."""

    @abstractmethod
    def serialize(self, value: Any) -> str:
        """The value as the string stored in a save."""

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

    # ------------------------------------------------------------------ operations

    def use_operation(self, operation, *values) -> Any:
        """Apply ``operation`` to ``values`` of this type (double dispatch, see :meth:`Operation.use`)."""
        return operation.use(self, *values)

    def __repr__(self) -> str:
        return f"<Datatype {self.name()}>"
