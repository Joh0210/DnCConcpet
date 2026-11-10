"""
Schnittstellen zwischen Engine und Ausdrücken.

Der Parser, der aus den YAML-Strings (``"2 * level + 1"``, ``entity.attributes[stat].value``)
typisierte ASTs baut, ist nicht Teil dieses Prototyps. Die Engine kennt nur diese
beiden Schnittstellen; zum Testen reichen Implementierungen mit Python-Funktionen
(siehe ``tests/fixtures.py``).

Ein Wert in einer Definition ist entweder ein Literal (``3``, ``"str"``, ``True``)
oder eine :class:`InnerFunction` — "a literal is a constant expression" (concept §4.4).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from Instance import Instance
    from property.Property import Property


class EvalContext:
    """
    Everything an expression can see while it evaluates.

    - ``this``: the instance the expression belongs to (an effect's source, a
      property's or container's owner). ``this.owner`` / ``this.entity`` lead
      further; both may be ``None`` while the instance is not attached.
    - ``previous``: the value so far (only meaningful for ``transform``).
    - ``it``: the candidate of an ``accepts`` predicate or a filter.
    - further names (``args``, ``action``, ...) as keywords.

    Read other values through ``Instance.get`` / ``Property.resolve`` — that is
    what registers the dependency, so the result is recomputed when they change.
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


class InnerFunction(ABC):
    """
    Quasi eine Funktion, welche immer genau auf einen Wert resolved.
    Diese Funktion bekommt dabei den aktuellen Kontext übergeben (``ctx.this`` ist die
    Instanz). Kann so also auf die Properties der Instanz zugreifen.

    Durch die entity-Funktion der Instanz kann sie auch auf das Entity zugreifen, sofern
    die Instanz contained ist. Hierbei muss allerdings auf None geachtet werden
    (im Ausdruck: ``entity?.level ?? 0``).
    """

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

    Der Pfad ist dabei wie folgt aufgebaut: der aktuelle Schritt, mit Optionen zur
    Verzweigung und co, und ein weiterer TargetPath.
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


def evaluate_value(value: Any, ctx: EvalContext) -> Any:
    """A literal as it is, an :class:`InnerFunction` evaluated in ``ctx``."""
    if isinstance(value, InnerFunction):
        return value.evaluate(ctx)
    return value


def describe_value(value: Any) -> str:
    """Readable form of a literal or an expression, for generated labels."""
    if isinstance(value, InnerFunction):
        return value.describe()
    return repr(value) if isinstance(value, str) else str(value)
