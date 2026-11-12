"""
Schnittstellen zwischen Engine und Ausdrücken.

Der Parser macht aus den YAML-Strings (``"2 * level + 1"``,
``entity.attributes[stat].value``) einen typisierten AST und schreibt ihn in die
JSON (concept §4.14). Die Engine parst nie selbst — sie baut aus dem JSON-AST
1:1 Knoten und wertet sie aus. Jeder Knoten ist ein VALUE::

    VALUE = STATIC_VALUE | OPERATION | PATH

- :class:`value.StaticValue.StaticValue` — ``{"value": "3", "type": "int"}``,
- :class:`value.OperationValue.OperationValue` — ``{"op": "add", "args": [VALUE, ...]}``,
- :class:`value.PathValue.PathValue` — ``{"path": [STEP, ...], "type": "int"}``.

Alle drei sind :class:`InnerFunction`; ein Pfad ist zusätzlich ein
:class:`TargetPath`. Gebaut werden sie von :func:`value.build_value`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from Instance import Instance
    from datatype.Datatype import Datatype
    from property.Property import Property


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
        try:
            return self.extra[name]
        except KeyError:
            raise AttributeError(f"expression context has no '{name}'") from None

    def var(self, name: str) -> Any:
        """The value a path starts at: ``this``, ``it``, ``previous`` or an extra name."""
        if name == "this":
            return self.this
        if name == "it":
            return self.it
        if name == "previous":
            return self.previous
        return getattr(self, name)

    def with_it(self, it: Any) -> EvalContext:
        """The same context with another candidate ``it`` (filters)."""
        return EvalContext(self.this, self.previous, it, **self.extra)


class InnerFunction(ABC):
    """
    Quasi eine Funktion, welche immer genau auf einen Wert resolved — ein Knoten
    des Ausdrucks-AST (ein VALUE). Sie bekommt den aktuellen Kontext übergeben
    (``ctx.this`` ist die Instanz), kann also auf die Properties der Instanz und
    über ``owner`` / ``entity`` auf ihre Umgebung zugreifen.

    Jeder Knoten hat einen **statischen Typ** (:attr:`type`), der schon beim
    Bauen feststeht — Operationen werden deshalb einmal beim Laden aufgelöst,
    nicht bei jeder Auswertung. Knoten sind unveränderlich und hängen an keiner
    Instanz: ein gebauter Baum wird von allen Instanzen einer Definition geteilt.
    """

    #: The static type of every value this node evaluates to (``None`` only for a target-only path).
    type: Datatype | None
    #: How tightly the node binds when it is written as text; atoms bind tightest.
    precedence: int = 10
    #: Whether the node is a :class:`value.StaticValue.StaticValue` (templates write those inline).
    is_literal: bool = False

    @abstractmethod
    def evaluate(self, ctx: EvalContext) -> Any:
        """The value of the expression in ``ctx``. Must be pure: never change values or structure."""

    def describe(self) -> str:
        """Source text of the expression, for labels, traces and error messages."""
        return type(self).__name__


class TargetPath(ABC):
    """
    Relevant für Auswertungen und Bestimmung von Targets bei Manipulationen und co.

    Ein TargetPath ist eine Liste von Schritten, die man braucht, um vom aktuellen Punkt
    (der Quelle des Effekts) zum Target zu kommen. Ein TargetPath führt dabei immer zu
    Properties — zu einer (``owner.damage``) oder zu mehreren
    (``entity.attributes[.str, .dex].advantage``, ``entity.inventory[is weapon].weight``).

    Verzweigungen sind Schritte, die aus einem Knoten mehrere machen (``[*]``,
    mehrere Keys, Filter); der Rest des Pfads gilt dann für jeden Zweig.
    Umgesetzt von :class:`value.PathValue.PathValue`.
    """

    @abstractmethod
    def resolve(self, source: Instance) -> list[Property]:
        """
        Every property the path addresses from ``source`` right now. A path that
        does not resolve (unattached, missing key, no match) returns ``[]`` — the
        effect is then inert (concept §4.6: targets need no ``?.``).
        """

    def describe(self) -> str:
        return type(self).__name__
