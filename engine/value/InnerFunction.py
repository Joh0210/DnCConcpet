"""
Interfaces between the engine and expressions.

The parser turns the YAML strings (``"2 * level + 1"``,
``entity.attributes[stat].value``) into a typed AST and writes it into the JSON
(concept §4.14). The engine never parses — it builds one node per JSON node and
evaluates it. Every node is a VALUE::

    VALUE = STATIC_VALUE | OPERATION | PATH

- :class:`engine.value.StaticValue.StaticValue` — ``{"value": "3", "type": "int"}``,
- :class:`engine.value.OperationValue.OperationValue` — ``{"op": "add", "args": [VALUE, ...]}``,
- :class:`engine.value.PathValue.PathValue` — ``{"path": [STEP, ...], "type": "int"}``.

All three are an :class:`InnerFunction`; a path is a :class:`TargetPath` as well.
They are built by :func:`engine.value.build.build_value`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from engine.datatype.Datatype import Datatype
    from engine.instance.Instance import Instance
    from engine.property.Property import Property


class EvalContext:
    """
    Everything an expression can see while it evaluates.

    - ``this``: the instance the expression belongs to (an effect's source, a
      property's or container's owner). ``this.owner`` / ``this.entity`` lead
      further; both may be ``None`` while the instance is not attached.
    - ``previous``: the value so far (only meaningful for ``transform``).
    - ``it``: the candidate of an ``accepts`` predicate or a ``where`` filter.
    - further names (``args``, ``action``, ...) as keywords.

    A path starts at one of these (``"from"``, default ``this``). It reads other
    values through ``Property.resolve`` / tracked container reads — that is what
    registers the dependency, so the result is recomputed when they change.
    """

    __slots__ = ("this", "previous", "it", "extra")

    def __init__(self, this: Instance | None, previous: Any = None, it: Any = None, **extra: Any):
        self.this = this
        self.previous = previous
        self.it = it
        self.extra = extra

    def __getattr__(self, name: str) -> Any:
        # Only called for names that are not slots: the extra names of the context.
        try:
            return self.extra[name]
        except KeyError:
            raise AttributeError(f"expression context has no '{name}'") from None

    def var(self, name: str) -> Any:
        """The value a path starts at: ``this``, ``it``, ``previous`` or an extra name."""
        return getattr(self, name)

    def with_it(self, it: Any) -> EvalContext:
        """The same context with another candidate ``it`` (filters)."""
        return EvalContext(self.this, self.previous, it, **self.extra)


class InnerFunction(ABC):
    """
    A function that always resolves to exactly one value — one node of the
    expression AST (a VALUE). It gets the current context (``ctx.this`` is the
    instance), so it can read the instance's props and, through ``owner`` /
    ``entity``, its surroundings.

    Every node has a **static type** (:attr:`type`), known when it is built — so
    operations are resolved once when the definition loads, not on every
    evaluation. Nodes are immutable and belong to no instance: a built tree is
    shared by every instance of a definition.
    """

    #: The static type of every value this node evaluates to (``None`` only for a target-only path).
    type: Datatype | None
    #: How tightly the node binds when it is written as text; atoms bind tightest.
    precedence: int = 10
    #: Whether the node is a :class:`engine.value.StaticValue.StaticValue` (templates write those inline).
    is_literal: bool = False

    @abstractmethod
    def evaluate(self, ctx: EvalContext) -> Any:
        """The value of the expression in ``ctx``. Must be pure: never change values or structure."""

    def describe(self) -> str:
        """Source text of the expression, for labels, traces and error messages."""
        return type(self).__name__


class TargetPath(ABC):
    """
    Where an effect goes: the steps from the effect's source to its targets.
    A target path always ends at properties — one (``owner.damage``) or several
    (``entity.attributes[.str, .dex].advantage``, ``entity.inventory[is weapon].weight``).

    Branching steps turn one node into several (``[*]``, several keys,
    filters); the rest of the path applies to every branch.
    Implemented by :class:`engine.value.PathValue.PathValue`.
    """

    @abstractmethod
    def resolve(self, source: Instance) -> list[Property]:
        """
        Every property the path addresses from ``source`` right now. A path that
        does not resolve (unattached, missing key, no match) returns ``[]`` — the
        effect is then inert (concept §4.6: targets need no ``?.``).
        """

    def describe(self) -> str:
        """The path as source text, for traces and error messages."""
        return type(self).__name__
